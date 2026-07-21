//! M1 — GPU shader compositor. Layers are BGRA textures (from the frame server);
//! each draw is a quad with a dest box + uv window (cover-crop), blended premultiplied.
//! Pop-out = color texture × matte texture (alpha from matte luma) in ONE pass — the
//! same math the bake pipeline uses, now live on the GPU.

use anyhow::{anyhow, Result};
use windows::core::PCSTR;
use windows::Win32::Graphics::Direct3D::Fxc::D3DCompile;
use windows::Win32::Graphics::Direct3D::ID3DBlob;
use windows::Win32::Graphics::Direct3D::D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP;
use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::*;

use crate::media::D3d;

pub type CaptionTex = (ID3D11Texture2D, (u32, u32), (f64, f64, f64, f64), f64);

const HLSL: &str = r#"
cbuffer CB : register(b0) { float4 dst; float4 uvr; float4 aff; float4 opt; };
struct VOut { float4 pos: SV_Position; float2 uv: TEXCOORD0; };
VOut vs(uint id: SV_VertexID) {
  float2 corners[4] = { float2(0,0), float2(1,0), float2(0,1), float2(1,1) };
  float2 c = corners[id];
  VOut o;
  float2 p = float2(dst.x + c.x * dst.z, dst.y + c.y * dst.w);
  o.pos = float4(p.x * 2 - 1, 1 - p.y * 2, 0, 1);
  o.uv = uvr.xy + c * uvr.zw;
  return o;
}
Texture2D tex0 : register(t0);
Texture2D tex1 : register(t1);
Texture2D tex2 : register(t2);
Texture2D tex3 : register(t3);
SamplerState smp : register(s0);
float4 ps_plain(VOut i) : SV_Target {
  float4 c = tex0.Sample(smp, i.uv);
  return float4(c.rgb * opt.x, opt.x);
}
float4 ps_alpha(VOut i) : SV_Target {
  float4 c = tex0.Sample(smp, i.uv);
  return float4(c.rgb * c.a * opt.x, c.a * opt.x);
}
float4 ps_popout(VOut i) : SV_Target {
  float3 c = tex0.Sample(smp, i.uv).rgb;
  float a = tex1.Sample(smp, i.uv).r;
  return float4(c * a * opt.x, a * opt.x);
}
// LIVE pop-out: color from the ORIGINAL frame (t0, full frame rate — the lips), person
// alpha (t1) + contact-shadow base (t2) from the baked matte twin, card geometry from the
// static mask texture (t3: R=rounded card, G=rim band, B=drop shadow). The 5 composite
// steps are popout_overlay.py's, evaluated per pixel. uv = bake canvas space;
// aff = (src0.xy, srcsize.zw) maps canvas uv -> original uv.
float4 ps_mosaic(VOut i) : SV_Target {
  // i.uv is FRAME-space (uvr window applied by the VS) — convert to region-local before
  // quantizing, then map back. Quantizing frame-space uv directly re-applied the uvr
  // window twice and showed a ZOOMED sub-window of the region instead of a mosaic.
  float2 local = (i.uv - uvr.xy) / max(uvr.zw, 1e-6);
  float2 cell = floor(local * aff.xy) / max(aff.xy, 1.0);
  float2 fuv = uvr.xy + (cell + 0.5 / max(aff.xy, 1.0)) * uvr.zw;
  return float4(tex0.Sample(smp, fuv).rgb, 1.0);
}
// Soft blur: 13-tap poisson disk over the canvas scratch — a smooth haze rather than a
// hard pixel grid. aff.xy = blur radius in CANVAS uv units (x, y).
float3 soft_blur(float2 cuv, float2 r) {
  static const float2 taps[12] = {
    float2(-0.326,-0.406), float2(-0.840,-0.074), float2(-0.696, 0.457),
    float2(-0.203, 0.621), float2( 0.962,-0.195), float2( 0.473,-0.480),
    float2( 0.519, 0.767), float2( 0.185,-0.893), float2( 0.507, 0.064),
    float2( 0.896, 0.412), float2(-0.322,-0.933), float2(-0.792,-0.598)
  };
  float3 acc = tex0.Sample(smp, cuv).rgb;
  [unroll] for (int k = 0; k < 12; k++) {
    acc += tex0.Sample(smp, cuv + taps[k] * r).rgb;         // outer ring
    acc += tex0.Sample(smp, cuv + taps[k] * r * 0.45).rgb;  // inner ring
  }
  return acc / 25.0;
}
// SAM tracked blur: quad over the BASE clip's dest box. t0 = canvas scratch copy,
// t1 = the baked mask video frame (SOURCE-frame space; blur weight in luma). uv (via
// uvr) walks the source/mask cover-crop window — the same mapping the base draw used —
// while the canvas is sampled by pixel position (aff.zw = canvas size).
float4 ps_blur_masked(VOut i) : SV_Target {
  float m = tex1.Sample(smp, i.uv).r;
  float2 cuv = i.pos.xy / aff.zw;
  float3 base = tex0.Sample(smp, cuv).rgb;
  if (m < 0.004) return float4(base, 1.0);
  float3 blurc = soft_blur(cuv, aff.xy);
  return float4(lerp(base, blurc, saturate(m)), 1.0);
}
// Static-rectangle soft blur (the un-baked stand-in and the "gaussian" style preview):
// THE RECT IS THE BLUR — full strength inside, nothing outside, no feather. The rule
// never bends with position or size (an outward fade LOOKED like a position-dependent
// offset when the canvas edge clipped one side of the halo), and it matches the
// export's uniform crop-blur exactly.
float4 ps_blur_rect(VOut i) : SV_Target {
  float2 cuv = i.pos.xy / aff.zw;
  float2 local = (cuv - uvr.xy) / max(uvr.zw, 1e-6);
  float3 base = tex0.Sample(smp, cuv).rgb;
  if (any(local < 0.0) || any(local > 1.0)) return float4(base, 1.0);
  float3 blurc = soft_blur(cuv, aff.xy);
  return float4(blurc, 1.0);
}
// A static redaction card. opt = RGB + opacity, with premultiplied-alpha output.
float4 ps_solid_rect(VOut i) : SV_Target {
  return float4(opt.rgb * opt.a, opt.a);
}
// Colour redaction following a SAM matte (tex1). The output is the final opaque
// canvas colour, preserving clean anti-aliased edges while the object moves.
float4 ps_solid_masked(VOut i) : SV_Target {
  float m = saturate(tex1.Sample(smp, i.uv).r * opt.a);
  float2 cuv = i.pos.xy / aff.zw;
  float3 base = tex0.Sample(smp, cuv).rgb;
  return float4(lerp(base, opt.rgb, m), 1.0);
}
float4 ps_popout_live(VOut i) : SV_Target {
  float3 msk = tex3.Sample(smp, i.uv).rgb;
  float ca = msk.r, bf = msk.g, drop = msk.b;
  float pa = tex1.Sample(smp, i.uv).r;
  float shb = tex2.Sample(smp, i.uv).r;
  float2 suv = (i.uv - aff.xy) / aff.zw;
  float inside = (suv.x >= 0 && suv.x <= 1 && suv.y >= 0 && suv.y <= 1) ? 1.0 : 0.0;
  float3 src = tex0.Sample(smp, saturate(suv)).rgb * inside;
  // 1. card drop shadow  2. card content over it
  float outa = drop * 0.45;
  float na = ca + outa * (1 - ca);
  float3 rgb = src * ca / max(na, 1e-6);
  outa = na;
  // 3. thin light rim on the card edge (never over the person)
  float be = bf * (1 - pa) * 0.6;
  rgb = rgb * (1 - be) + float3(0.8235, 0.7647, 0.7843) * be; // border_col 210,195,200 RGB
  outa = saturate(outa + be);
  // (contact shadow removed by user request: it read as a black ring around the body
  //  plus a flickering translucent silhouette behind it — no shadow, clean cutout)
  // 5. person on top; premultiplied out
  float nna = outa + pa * (1 - outa);
  rgb = (rgb * outa * (1 - pa) + src * pa) / max(nna, 1e-6);
  return float4(rgb * nna * opt.x, nna * opt.x);
}
"#;

/// Separable gaussian, radius = round(σ·4), zero padding — bit-matches the bake's
/// gauss_blur (torch conv2d) so the live card look equals the baked one.
fn gauss_inplace(buf: &mut [f32], w: usize, h: usize, sigma: f64) {
    let radius = (sigma * 4.0).round().max(1.0) as i32;
    let mut k = Vec::with_capacity((radius * 2 + 1) as usize);
    for x in -radius..=radius {
        k.push((-(x as f64 * x as f64) / (2.0 * sigma * sigma)).exp());
    }
    let s: f64 = k.iter().sum();
    let k: Vec<f32> = k.iter().map(|v| (v / s) as f32).collect();
    let mut tmp = vec![0f32; w * h];
    for y in 0..h {
        let row = &buf[y * w..(y + 1) * w];
        for x in 0..w as i32 {
            let mut acc = 0f32;
            for (i, kv) in k.iter().enumerate() {
                let sx = x + i as i32 - radius;
                if sx >= 0 && sx < w as i32 {
                    acc += row[sx as usize] * kv;
                }
            }
            tmp[y * w + x as usize] = acc;
        }
    }
    for y in 0..h as i32 {
        for x in 0..w {
            let mut acc = 0f32;
            for (i, kv) in k.iter().enumerate() {
                let sy = y + i as i32 - radius;
                if sy >= 0 && sy < h as i32 {
                    acc += tmp[sy as usize * w + x] * kv;
                }
            }
            buf[y as usize * w + x] = acc;
        }
    }
}

fn compile(entry: &str, target: &str) -> Result<ID3DBlob> {
    unsafe {
        let mut blob: Option<ID3DBlob> = None;
        let mut err: Option<ID3DBlob> = None;
        let e = std::ffi::CString::new(entry).unwrap();
        let t = std::ffi::CString::new(target).unwrap();
        let r = D3DCompile(
            HLSL.as_ptr() as _,
            HLSL.len(),
            None,
            None,
            None,
            PCSTR(e.as_ptr() as _),
            PCSTR(t.as_ptr() as _),
            0,
            0,
            &mut blob,
            Some(&mut err),
        );
        if r.is_err() {
            let msg = err
                .map(|b| {
                    String::from_utf8_lossy(std::slice::from_raw_parts(
                        b.GetBufferPointer() as *const u8,
                        b.GetBufferSize(),
                    ))
                    .to_string()
                })
                .unwrap_or_default();
            return Err(anyhow!("shader compile {entry}: {msg}"));
        }
        Ok(blob.unwrap())
    }
}

#[repr(C)]
#[derive(Clone, Copy)]
struct Cb {
    dst: [f32; 4],
    uvr: [f32; 4],
    aff: [f32; 4],
    opt: [f32; 4],
}

pub struct Compositor {
    pub width: u32,
    pub height: u32,
    canvas: ID3D11Texture2D,
    rtv: ID3D11RenderTargetView,
    staging: [ID3D11Texture2D; 3],
    staging_i: usize,
    staging_filled: usize,
    vs: ID3D11VertexShader,
    ps_plain: ID3D11PixelShader,
    ps_alpha: ID3D11PixelShader,
    ps_popout: ID3D11PixelShader,
    ps_popout_live: ID3D11PixelShader,
    ps_mosaic: ID3D11PixelShader,
    ps_blur_masked: ID3D11PixelShader,
    ps_blur_rect: ID3D11PixelShader,
    ps_solid_rect: ID3D11PixelShader,
    ps_solid_masked: ID3D11PixelShader,
    scratch: std::cell::RefCell<Option<ID3D11Texture2D>>,
    // freeze-frame stills: (source path, src ms) -> a private copy of the decoded frame.
    // A freeze clip re-requesting the SAME source time every frame kept fighting the
    // ping-pong decoder instances with its neighbours (measured as stutter around the
    // freeze) — one decode, one copy, zero pool traffic afterwards.
    stills: std::cell::RefCell<std::collections::HashMap<(String, i64), (ID3D11Texture2D, (u32, u32))>>,
    caption_stills: std::cell::RefCell<std::collections::HashMap<String, CaptionTex>>,
    caption_by_clip: std::cell::RefCell<std::collections::HashMap<String, String>>,
    cb: ID3D11Buffer,
    sampler: ID3D11SamplerState,
    blend: ID3D11BlendState,
    pub rgba: Vec<u8>, // last readback, RGBA
}

impl Compositor {
    pub fn new(d3d: &D3d, width: u32, height: u32) -> Result<Self> {
        unsafe {
            let desc = D3D11_TEXTURE2D_DESC {
                Width: width,
                Height: height,
                MipLevels: 1,
                ArraySize: 1,
                Format: DXGI_FORMAT_B8G8R8A8_UNORM,
                SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_DEFAULT,
                BindFlags: (D3D11_BIND_RENDER_TARGET.0 | D3D11_BIND_SHADER_RESOURCE.0) as u32,
                ..Default::default()
            };
            let mut canvas: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, None, Some(&mut canvas))?;
            let canvas = canvas.unwrap();
            let mut rtv: Option<ID3D11RenderTargetView> = None;
            d3d.device.CreateRenderTargetView(&canvas, None, Some(&mut rtv))?;
            let sdesc = D3D11_TEXTURE2D_DESC {
                Usage: D3D11_USAGE_STAGING,
                BindFlags: 0,
                CPUAccessFlags: D3D11_CPU_ACCESS_READ.0 as u32,
                ..desc
            };
            let mut staging0: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&sdesc, None, Some(&mut staging0))?;
            let mut staging1: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&sdesc, None, Some(&mut staging1))?;
            let mut staging2: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&sdesc, None, Some(&mut staging2))?;

            let vsb = compile("vs", "vs_5_0")?;
            let psb1 = compile("ps_plain", "ps_5_0")?;
            let psba = compile("ps_alpha", "ps_5_0")?;
            let psb2 = compile("ps_popout", "ps_5_0")?;
            let psb4 = compile("ps_mosaic", "ps_5_0")?;
            let psb3 = compile("ps_popout_live", "ps_5_0")?;
            let bytes = |b: &ID3DBlob| std::slice::from_raw_parts(b.GetBufferPointer() as *const u8, b.GetBufferSize());
            let mut ps_mosaic: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb4), None, Some(&mut ps_mosaic))?;
            let psb5 = compile("ps_blur_masked", "ps_5_0")?;
            let mut ps_blur_masked: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb5), None, Some(&mut ps_blur_masked))?;
            let psb6 = compile("ps_blur_rect", "ps_5_0")?;
            let mut ps_blur_rect: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb6), None, Some(&mut ps_blur_rect))?;
            let psb7 = compile("ps_solid_rect", "ps_5_0")?;
            let mut ps_solid_rect: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb7), None, Some(&mut ps_solid_rect))?;
            let psb8 = compile("ps_solid_masked", "ps_5_0")?;
            let mut ps_solid_masked: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb8), None, Some(&mut ps_solid_masked))?;
            let mut vs: Option<ID3D11VertexShader> = None;
            d3d.device.CreateVertexShader(bytes(&vsb), None, Some(&mut vs))?;
            let mut ps_plain: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb1), None, Some(&mut ps_plain))?;
            let mut ps_alpha: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psba), None, Some(&mut ps_alpha))?;
            let mut ps_popout: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb2), None, Some(&mut ps_popout))?;
            let mut ps_popout_live: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb3), None, Some(&mut ps_popout_live))?;

            let cbd = D3D11_BUFFER_DESC {
                ByteWidth: std::mem::size_of::<Cb>() as u32,
                Usage: D3D11_USAGE_DEFAULT,
                BindFlags: D3D11_BIND_CONSTANT_BUFFER.0 as u32,
                ..Default::default()
            };
            let mut cb: Option<ID3D11Buffer> = None;
            d3d.device.CreateBuffer(&cbd, None, Some(&mut cb))?;

            let mut sampler: Option<ID3D11SamplerState> = None;
            d3d.device.CreateSamplerState(
                &D3D11_SAMPLER_DESC {
                    Filter: D3D11_FILTER_MIN_MAG_MIP_LINEAR,
                    AddressU: D3D11_TEXTURE_ADDRESS_CLAMP,
                    AddressV: D3D11_TEXTURE_ADDRESS_CLAMP,
                    AddressW: D3D11_TEXTURE_ADDRESS_CLAMP,
                    MaxLOD: f32::MAX,
                    ..Default::default()
                },
                Some(&mut sampler),
            )?;

            let mut bdesc = D3D11_BLEND_DESC::default();
            bdesc.RenderTarget[0] = D3D11_RENDER_TARGET_BLEND_DESC {
                BlendEnable: true.into(),
                SrcBlend: D3D11_BLEND_ONE,
                DestBlend: D3D11_BLEND_INV_SRC_ALPHA,
                BlendOp: D3D11_BLEND_OP_ADD,
                SrcBlendAlpha: D3D11_BLEND_ONE,
                DestBlendAlpha: D3D11_BLEND_INV_SRC_ALPHA,
                BlendOpAlpha: D3D11_BLEND_OP_ADD,
                RenderTargetWriteMask: D3D11_COLOR_WRITE_ENABLE_ALL.0 as u8,
            };
            let mut blend: Option<ID3D11BlendState> = None;
            d3d.device.CreateBlendState(&bdesc, Some(&mut blend))?;

            Ok(Self {
                width,
                height,
                canvas,
                rtv: rtv.unwrap(),
                staging: [staging0.unwrap(), staging1.unwrap(), staging2.unwrap()],
                staging_i: 0,
                staging_filled: 0,
                vs: vs.unwrap(),
                ps_plain: ps_plain.unwrap(),
                ps_alpha: ps_alpha.unwrap(),
                ps_popout: ps_popout.unwrap(),
                ps_popout_live: ps_popout_live.unwrap(),
                ps_mosaic: ps_mosaic.unwrap(),
                ps_blur_masked: ps_blur_masked.unwrap(),
                ps_blur_rect: ps_blur_rect.unwrap(),
                ps_solid_rect: ps_solid_rect.unwrap(),
                ps_solid_masked: ps_solid_masked.unwrap(),
                scratch: std::cell::RefCell::new(None),
                stills: std::cell::RefCell::new(Default::default()),
                caption_stills: std::cell::RefCell::new(Default::default()),
                caption_by_clip: std::cell::RefCell::new(Default::default()),
                cb: cb.unwrap(),
                sampler: sampler.unwrap(),
                blend: blend.unwrap(),
                rgba: vec![0u8; (width * height * 4) as usize],
            })
        }
    }

    pub fn begin(&self, d3d: &D3d) {
        unsafe {
            d3d.ctx.OMSetRenderTargets(Some(&[Some(self.rtv.clone())]), None);
            d3d.ctx.ClearRenderTargetView(&self.rtv, &[0.0, 0.0, 0.0, 1.0]);
            d3d.ctx.RSSetViewports(Some(&[D3D11_VIEWPORT {
                Width: self.width as f32,
                Height: self.height as f32,
                MaxDepth: 1.0,
                ..Default::default()
            }]));
            d3d.ctx.IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
            d3d.ctx.VSSetShader(&self.vs, None);
            d3d.ctx.PSSetSamplers(0, Some(&[Some(self.sampler.clone())]));
            d3d.ctx.OMSetBlendState(&self.blend, None, 0xffff_ffff);
            d3d.ctx.VSSetConstantBuffers(0, Some(&[Some(self.cb.clone())]));
            d3d.ctx.PSSetConstantBuffers(0, Some(&[Some(self.cb.clone())]));
        }
    }

    /// Draw into a canvas box. `cover` preserves source aspect and crops overflow;
    /// `opacity` is applied in the same premultiplied-alpha pass.
    #[allow(clippy::too_many_arguments)]
    pub fn draw_opacity(
        &self,
        d3d: &D3d,
        tex: &ID3D11Texture2D,
        src_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        cover: bool,
        matte: Option<&ID3D11Texture2D>,
        opacity: f32,
    ) -> Result<()> {
        self.draw_cropped_opacity(d3d, tex, src_wh, dst, cover, matte, None, opacity)
    }

    pub fn draw_alpha_opacity(
        &self,
        d3d: &D3d,
        tex: &ID3D11Texture2D,
        src_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        opacity: f32,
    ) -> Result<()> {
        self.draw_with_shader(d3d, tex, src_wh, dst, false, None, None, Some(&self.ps_alpha), opacity)
    }

    /// Per-edge MASK crop: trimmed strips reveal the background; kept pixels stay put.
    #[allow(clippy::too_many_arguments)]
    pub fn draw_cropped_opacity(
        &self,
        d3d: &D3d,
        tex: &ID3D11Texture2D,
        src_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        cover: bool,
        matte: Option<&ID3D11Texture2D>,
        crop: Option<(f64, f64, f64, f64)>,
        opacity: f32,
    ) -> Result<()> {
        self.draw_with_shader(d3d, tex, src_wh, dst, cover, matte, crop, None, opacity)
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_with_shader(
        &self,
        d3d: &D3d,
        tex: &ID3D11Texture2D,
        src_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        cover: bool,
        matte: Option<&ID3D11Texture2D>,
        crop: Option<(f64, f64, f64, f64)>,
        shader: Option<&ID3D11PixelShader>,
        opacity: f32,
    ) -> Result<()> {
        let mut dst = dst;
        unsafe {
            let mut srv0: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(tex, None, Some(&mut srv0))?;
            let mut views = vec![srv0];
            if let Some(m) = matte {
                let mut srv1: Option<ID3D11ShaderResourceView> = None;
                d3d.device.CreateShaderResourceView(m, None, Some(&mut srv1))?;
                views.push(srv1);
            }
            // cover-crop uv window
            let (mut u0, mut v0, mut uw, mut vh) = (0.0f32, 0.0f32, 1.0f32, 1.0f32);
            if cover {
                let box_px_w = dst.2 * self.width as f64;
                let box_px_h = dst.3 * self.height as f64;
                if box_px_w > 1.0 && box_px_h > 1.0 {
                    let sa = src_wh.0 as f64 / src_wh.1 as f64;
                    let da = box_px_w / box_px_h;
                    if sa > da {
                        let keep = da / sa;
                        u0 = ((1.0 - keep) / 2.0) as f32;
                        uw = keep as f32;
                    } else {
                        let keep = sa / da;
                        v0 = ((1.0 - keep) / 2.0) as f32;
                        vh = keep as f32;
                    }
                }
            }
            if let Some((l, t, r, b)) = crop {
                // shrink the uv window INSIDE the cover window and the dest box in step
                u0 += uw * l as f32;
                v0 += vh * t as f32;
                uw *= (1.0 - l - r).max(0.02) as f32;
                vh *= (1.0 - t - b).max(0.02) as f32;
                dst = (
                    dst.0 + dst.2 * l,
                    dst.1 + dst.3 * t,
                    dst.2 * (1.0 - l - r).max(0.02),
                    dst.3 * (1.0 - t - b).max(0.02),
                );
            }
            let cbv = Cb {
                dst: [dst.0 as f32, dst.1 as f32, dst.2 as f32, dst.3 as f32],
                uvr: [u0, v0, uw, vh],
                aff: [0.0, 0.0, 1.0, 1.0],
                opt: [opacity.clamp(0.0, 1.0), 0.0, 0.0, 0.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&views));
            let ps = shader.unwrap_or(if matte.is_some() { &self.ps_popout } else { &self.ps_plain });
            d3d.ctx.PSSetShader(ps, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// LIVE pop-out draw: original frame + matte twin (person α / shadow base) + static
    /// card-mask texture, composited by ps_popout_live into the dest box.
    /// `aff` = (src_x/W, src_y/H, sw/W, sh/H) — canvas uv -> original uv.
    pub fn draw_popout_live(
        &self,
        d3d: &D3d,
        orig: &ID3D11Texture2D,
        person: &ID3D11Texture2D,
        shadow: &ID3D11Texture2D,
        mask: &ID3D11Texture2D,
        dst: (f64, f64, f64, f64),
        aff: [f32; 4],
        opacity: f32,
    ) -> Result<()> {
        unsafe {
            let mut views: Vec<Option<ID3D11ShaderResourceView>> = Vec::with_capacity(4);
            for tex in [orig, person, shadow, mask] {
                let mut srv: Option<ID3D11ShaderResourceView> = None;
                d3d.device.CreateShaderResourceView(tex, None, Some(&mut srv))?;
                views.push(srv);
            }
            let cbv = Cb {
                dst: [dst.0 as f32, dst.1 as f32, dst.2 as f32, dst.3 as f32],
                uvr: [0.0, 0.0, 1.0, 1.0],
                aff,
                opt: [opacity.clamp(0.0, 1.0), 0.0, 0.0, 0.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&views));
            d3d.ctx.PSSetShader(&self.ps_popout_live, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// Build the static card-mask texture for one pop-out bake (R=rounded card, G=rim
    /// band, B=drop shadow) from its meta — the same math popout_overlay.py runs once per
    /// bake. ~0.3s for the σ26 blur; call from idle only and cache per key.
    pub fn build_popout_mask(d3d: &D3d, meta: &crate::model::PopMeta) -> Result<ID3D11Texture2D> {
        let (w, h) = (meta.canvas[0] as usize, meta.canvas[1] as usize);
        let [px, py, ow, oh] = meta.bbox;
        let r = meta.radius.clamp(0, ow.min(oh) / 2) as f64;
        // card: hard-edged rounded rect (cv2 rectangle+circles equivalent)
        let mut ca = vec![0f32; w * h];
        for y in py.max(0)..(py + oh).min(h as i32) {
            for x in px.max(0)..(px + ow).min(w as i32) {
                let (lx, ly) = ((x - px) as f64, (y - py) as f64);
                let dx = (r - lx).max(lx - (ow as f64 - r)).max(0.0);
                let dy = (r - ly).max(ly - (oh as f64 - r)).max(0.0);
                if dx * dx + dy * dy <= r * r {
                    ca[y as usize * w + x as usize] = 1.0;
                }
            }
        }
        // rim: dilate3x3 - erode3x3 of the card, gauss σ1.2
        let mut border = vec![0f32; w * h];
        for y in 0..h as i32 {
            for x in 0..w as i32 {
                let (mut mn, mut mx) = (1.0f32, 0.0f32);
                for dy in -1..=1i32 {
                    for dx in -1..=1i32 {
                        let (nx, ny) = (x + dx, y + dy);
                        let v = if nx >= 0 && ny >= 0 && nx < w as i32 && ny < h as i32 {
                            ca[ny as usize * w + nx as usize]
                        } else {
                            0.0 // cv2 morphology pads with the border value ~0 here
                        };
                        mn = mn.min(v);
                        mx = mx.max(v);
                    }
                }
                border[y as usize * w + x as usize] = mx - mn;
            }
        }
        gauss_inplace(&mut border, w, h, 1.2);
        // drop shadow: gauss(card, σ26) rolled +16 rows/+6 cols (wrapping, like torch.roll),
        // minus the card, clamped
        let mut drop = ca.clone();
        gauss_inplace(&mut drop, w, h, 26.0);
        let mut rolled = vec![0f32; w * h];
        for y in 0..h {
            let sy = (y + h - 16) % h;
            for x in 0..w {
                let sx = (x + w - 6) % w;
                rolled[y * w + x] = drop[sy * w + sx];
            }
        }
        let mut rgba = vec![0u8; w * h * 4];
        for i in 0..w * h {
            let d = (rolled[i] - ca[i]).clamp(0.0, 1.0);
            rgba[i * 4] = (ca[i] * 255.0) as u8;
            rgba[i * 4 + 1] = (border[i].clamp(0.0, 1.0) * 255.0) as u8;
            rgba[i * 4 + 2] = (d * 255.0) as u8;
            rgba[i * 4 + 3] = 255;
        }
        unsafe {
            let desc = D3D11_TEXTURE2D_DESC {
                Width: w as u32,
                Height: h as u32,
                MipLevels: 1,
                ArraySize: 1,
                Format: DXGI_FORMAT_R8G8B8A8_UNORM,
                SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_IMMUTABLE,
                BindFlags: D3D11_BIND_SHADER_RESOURCE.0 as u32,
                ..Default::default()
            };
            let init = D3D11_SUBRESOURCE_DATA {
                pSysMem: rgba.as_ptr() as _,
                SysMemPitch: (w * 4) as u32,
                ..Default::default()
            };
            let mut tex: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, Some(&init), Some(&mut tex))?;
            Ok(tex.unwrap())
        }
    }

    /// Read the canvas back as RGBA. Live playback is triple-buffered: copy into
    /// staging[i], then map the oldest completed staging texture. Mapping the
    /// just-copied texture stalls on the in-flight GPU frame; mapping an older texture
    /// is usually a pure memcpy for a small preview-latency tradeoff.
    /// Region mosaic: copy the composed canvas, then redraw the region sampling the
    /// copy on a coarse grid (the live stand-in for the exporter's blur/mosaic pass).
    pub fn apply_mosaic(&self, d3d: &D3d, region: (f64, f64, f64, f64), cell_px: f64) -> Result<()> {
        unsafe {
            // lazy scratch copy of the canvas
            {
                let mut sc = self.scratch.borrow_mut();
                if sc.is_none() {
                    let mut desc = D3D11_TEXTURE2D_DESC::default();
                    self.canvas.GetDesc(&mut desc);
                    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE.0 as u32;
                    desc.Usage = D3D11_USAGE_DEFAULT;
                    desc.CPUAccessFlags = 0;
                    desc.MiscFlags = 0;
                    let mut t: Option<ID3D11Texture2D> = None;
                    d3d.device.CreateTexture2D(&desc, None, Some(&mut t))?;
                    *sc = t;
                }
                d3d.ctx.CopyResource(sc.as_ref().unwrap(), &self.canvas);
            }
            let sc = self.scratch.borrow();
            let scratch = sc.as_ref().unwrap();
            let mut srv: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(scratch, None, Some(&mut srv))?;
            let (x, y, w, h) = region;
            let cells_x = ((w * self.width as f64) / cell_px).max(2.0) as f32;
            let cells_y = ((h * self.height as f64) / cell_px).max(2.0) as f32;
            let cbv = Cb {
                dst: [x as f32, y as f32, w as f32, h as f32],
                uvr: [x as f32, y as f32, w as f32, h as f32],
                aff: [cells_x, cells_y, 0.0, 0.0],
                opt: [1.0, 0.0, 0.0, 0.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&[srv]));
            d3d.ctx.PSSetShader(&self.ps_mosaic, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// SAM tracked blur over the base clip's area: mixes the canvas with its pixelated
    /// copy, weighted per pixel by the baked mask video frame (255 = fully blurred).
    /// The mask lives in the base clip's SOURCE-frame space, so the quad re-derives the
    /// same cover-crop uv window the base draw used (`mask_wh` carries the source aspect;
    /// `dst`/`crop` are the base clip's display box and crop).
    pub fn apply_blur_masked(
        &self,
        d3d: &D3d,
        mask: &ID3D11Texture2D,
        mask_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        crop: Option<(f64, f64, f64, f64)>,
        cell_px: f64,
    ) -> Result<()> {
        unsafe {
            {
                let mut sc = self.scratch.borrow_mut();
                if sc.is_none() {
                    let mut desc = D3D11_TEXTURE2D_DESC::default();
                    self.canvas.GetDesc(&mut desc);
                    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE.0 as u32;
                    desc.Usage = D3D11_USAGE_DEFAULT;
                    desc.CPUAccessFlags = 0;
                    desc.MiscFlags = 0;
                    let mut t: Option<ID3D11Texture2D> = None;
                    d3d.device.CreateTexture2D(&desc, None, Some(&mut t))?;
                    *sc = t;
                }
                d3d.ctx.CopyResource(sc.as_ref().unwrap(), &self.canvas);
            }
            let sc = self.scratch.borrow();
            let scratch = sc.as_ref().unwrap();
            let mut srv0: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(scratch, None, Some(&mut srv0))?;
            let mut srv1: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(mask, None, Some(&mut srv1))?;
            // identical cover-crop window math to draw_with_shader (the base clip's draw)
            let mut dst = dst;
            let (mut u0, mut v0, mut uw, mut vh) = (0.0f32, 0.0f32, 1.0f32, 1.0f32);
            let box_px_w = dst.2 * self.width as f64;
            let box_px_h = dst.3 * self.height as f64;
            if box_px_w > 1.0 && box_px_h > 1.0 {
                let sa = mask_wh.0 as f64 / mask_wh.1 as f64;
                let da = box_px_w / box_px_h;
                if sa > da {
                    let keep = da / sa;
                    u0 = ((1.0 - keep) / 2.0) as f32;
                    uw = keep as f32;
                } else {
                    let keep = sa / da;
                    v0 = ((1.0 - keep) / 2.0) as f32;
                    vh = keep as f32;
                }
            }
            if let Some((l, t, r, b)) = crop {
                u0 += uw * l as f32;
                v0 += vh * t as f32;
                uw *= (1.0 - l - r).max(0.02) as f32;
                vh *= (1.0 - t - b).max(0.02) as f32;
                dst = (
                    dst.0 + dst.2 * l,
                    dst.1 + dst.3 * t,
                    dst.2 * (1.0 - l - r).max(0.02),
                    dst.3 * (1.0 - t - b).max(0.02),
                );
            }
            let cbv = Cb {
                dst: [dst.0 as f32, dst.1 as f32, dst.2 as f32, dst.3 as f32],
                uvr: [u0, v0, uw, vh],
                // aff.xy = soft-blur radius in canvas uv, aff.zw = canvas pixel size
                aff: [
                    (cell_px / self.width as f64) as f32,
                    (cell_px / self.height as f64) as f32,
                    self.width as f32,
                    self.height as f32,
                ],
                opt: [1.0, 0.0, 0.0, 0.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&[srv0, srv1]));
            d3d.ctx.PSSetShader(&self.ps_blur_masked, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// Static-rectangle SOFT blur (the un-baked stand-in / "gaussian" style): same haze
    /// as the tracked path, gated to the drawn region.
    pub fn apply_blur_rect(&self, d3d: &D3d, region: (f64, f64, f64, f64), radius_px: f64) -> Result<()> {
        unsafe {
            {
                let mut sc = self.scratch.borrow_mut();
                if sc.is_none() {
                    let mut desc = D3D11_TEXTURE2D_DESC::default();
                    self.canvas.GetDesc(&mut desc);
                    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE.0 as u32;
                    desc.Usage = D3D11_USAGE_DEFAULT;
                    desc.CPUAccessFlags = 0;
                    desc.MiscFlags = 0;
                    let mut t: Option<ID3D11Texture2D> = None;
                    d3d.device.CreateTexture2D(&desc, None, Some(&mut t))?;
                    *sc = t;
                }
                d3d.ctx.CopyResource(sc.as_ref().unwrap(), &self.canvas);
            }
            let sc = self.scratch.borrow();
            let scratch = sc.as_ref().unwrap();
            let mut srv: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(scratch, None, Some(&mut srv))?;
            let (x, y, w, h) = region;
            let cbv = Cb {
                dst: [x as f32, y as f32, w as f32, h as f32],
                uvr: [x as f32, y as f32, w as f32, h as f32],
                aff: [
                    (radius_px / self.width as f64) as f32,
                    (radius_px / self.height as f64) as f32,
                    self.width as f32,
                    self.height as f32,
                ],
                opt: [1.0, 0.0, 0.0, 0.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&[srv]));
            d3d.ctx.PSSetShader(&self.ps_blur_rect, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// Opaque or translucent colour redaction over a static rectangle.
    pub fn apply_solid_rect(&self, d3d: &D3d, region: (f64, f64, f64, f64), color: [f32; 3], opacity: f64) -> Result<()> {
        unsafe {
            let (x, y, w, h) = region;
            let cbv = Cb {
                dst: [x as f32, y as f32, w as f32, h as f32], uvr: [0.0; 4], aff: [0.0; 4],
                opt: [color[0], color[1], color[2], opacity.clamp(0.0, 1.0) as f32],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShader(&self.ps_solid_rect, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }

    /// Colour redaction following a SAM-tracked matte.
    pub fn apply_solid_masked(
        &self, d3d: &D3d, mask: &ID3D11Texture2D, mask_wh: (u32, u32),
        dest: (f64, f64, f64, f64), crop: Option<(f64, f64, f64, f64)>,
        color: [f32; 3], opacity: f64,
    ) -> Result<()> {
        unsafe {
            {
                let mut sc = self.scratch.borrow_mut();
                if sc.is_none() {
                    let mut desc = D3D11_TEXTURE2D_DESC::default(); self.canvas.GetDesc(&mut desc);
                    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE.0 as u32; desc.Usage = D3D11_USAGE_DEFAULT;
                    desc.CPUAccessFlags = 0; desc.MiscFlags = 0;
                    let mut t: Option<ID3D11Texture2D> = None; d3d.device.CreateTexture2D(&desc, None, Some(&mut t))?; *sc = t;
                }
                d3d.ctx.CopyResource(sc.as_ref().unwrap(), &self.canvas);
            }
            let mut srv0: Option<ID3D11ShaderResourceView> = None;
            let mut srv1: Option<ID3D11ShaderResourceView> = None;
            d3d.device.CreateShaderResourceView(self.scratch.borrow().as_ref().unwrap(), None, Some(&mut srv0))?;
            d3d.device.CreateShaderResourceView(mask, None, Some(&mut srv1))?;
            let mut dst = dest;
            let (mut u0, mut v0, mut uw, mut vh) = (0.0f32, 0.0f32, 1.0f32, 1.0f32);
            let bw = dst.2 * self.width as f64; let bh = dst.3 * self.height as f64;
            if bw > 1.0 && bh > 1.0 {
                let sa = mask_wh.0 as f64 / mask_wh.1.max(1) as f64; let da = bw / bh;
                if sa > da { let keep = da / sa; u0 = ((1.0 - keep) / 2.0) as f32; uw = keep as f32; }
                else { let keep = sa / da; v0 = ((1.0 - keep) / 2.0) as f32; vh = keep as f32; }
            }
            if let Some((l, t, r, b)) = crop {
                u0 += uw * l as f32; v0 += vh * t as f32;
                uw *= (1.0 - l - r).max(0.02) as f32; vh *= (1.0 - t - b).max(0.02) as f32;
                dst = (dst.0 + dst.2 * l, dst.1 + dst.3 * t, dst.2 * (1.0 - l - r).max(0.02), dst.3 * (1.0 - t - b).max(0.02));
            }
            let cbv = Cb {
                dst: [dst.0 as f32, dst.1 as f32, dst.2 as f32, dst.3 as f32], uvr: [u0, v0, uw, vh],
                aff: [0.0, 0.0, self.width as f32, self.height as f32],
                opt: [color[0], color[1], color[2], opacity.clamp(0.0, 1.0) as f32],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&[srv0, srv1]));
            d3d.ctx.PSSetShader(&self.ps_solid_masked, None);
            d3d.ctx.Draw(4, 0);
            Ok(())
        }
    }
}

/// Forward mapping SOURCE-frame box -> CANVAS box (the cover-crop the base draw uses).
/// Used to place the tracked-object outline where the blur currently is.
pub fn source_box_to_canvas(
    canvas_wh: (u32, u32),
    src_wh: (u32, u32),
    dst: (f64, f64, f64, f64),
    cover: bool,
    crop: Option<(f64, f64, f64, f64)>,
    src_box: (f64, f64, f64, f64),
) -> (f64, f64, f64, f64) {
    let mut dst = dst;
    let (mut u0, mut v0, mut uw, mut vh) = (0.0f64, 0.0f64, 1.0f64, 1.0f64);
    let box_px_w = dst.2 * canvas_wh.0 as f64;
    let box_px_h = dst.3 * canvas_wh.1 as f64;
    if cover && box_px_w > 1.0 && box_px_h > 1.0 && src_wh.0 > 0 && src_wh.1 > 0 {
        let sa = src_wh.0 as f64 / src_wh.1 as f64;
        let da = box_px_w / box_px_h;
        if sa > da {
            uw = da / sa;
            u0 = (1.0 - uw) / 2.0;
        } else {
            vh = sa / da;
            v0 = (1.0 - vh) / 2.0;
        }
    }
    if let Some((l, t, r, b)) = crop {
        u0 += uw * l;
        v0 += vh * t;
        uw *= (1.0 - l - r).max(0.02);
        vh *= (1.0 - t - b).max(0.02);
        dst = (
            dst.0 + dst.2 * l,
            dst.1 + dst.3 * t,
            dst.2 * (1.0 - l - r).max(0.02),
            dst.3 * (1.0 - t - b).max(0.02),
        );
    }
    let fx = |sx: f64| dst.0 + ((sx - u0) / uw.max(1e-6)) * dst.2;
    let fy = |sy: f64| dst.1 + ((sy - v0) / vh.max(1e-6)) * dst.3;
    let x0 = fx(src_box.0);
    let y0 = fy(src_box.1);
    let x1 = fx(src_box.0 + src_box.2);
    let y1 = fy(src_box.1 + src_box.3);
    (x0, y0, (x1 - x0).max(0.0), (y1 - y0).max(0.0))
}

/// Point variant of canvas_box_to_source (correction clicks land on source pixels).
pub fn canvas_point_to_source(
    canvas_wh: (u32, u32),
    src_wh: (u32, u32),
    dst: (f64, f64, f64, f64),
    cover: bool,
    crop: Option<(f64, f64, f64, f64)>,
    p: (f64, f64),
) -> (f64, f64) {
    let b = canvas_box_to_source(canvas_wh, src_wh, dst, cover, crop, (p.0, p.1, 0.0, 0.0));
    (b.0, b.1)
}

/// Map a CANVAS-space box into the base clip's SOURCE-frame space (inverse of the
/// cover-crop mapping in draw_with_shader) — used to hand the user's drawn rectangle
/// to the SAM bake, which works on source pixels. Returns (x, y, w, h) normalized.
pub fn canvas_box_to_source(
    canvas_wh: (u32, u32),
    src_wh: (u32, u32),
    dst: (f64, f64, f64, f64),
    cover: bool,
    crop: Option<(f64, f64, f64, f64)>,
    canvas_box: (f64, f64, f64, f64),
) -> (f64, f64, f64, f64) {
    {
        let mut dst = dst;
        let (mut u0, mut v0, mut uw, mut vh) = (0.0f64, 0.0f64, 1.0f64, 1.0f64);
        let box_px_w = dst.2 * canvas_wh.0 as f64;
        let box_px_h = dst.3 * canvas_wh.1 as f64;
        if cover && box_px_w > 1.0 && box_px_h > 1.0 && src_wh.0 > 0 && src_wh.1 > 0 {
            let sa = src_wh.0 as f64 / src_wh.1 as f64;
            let da = box_px_w / box_px_h;
            if sa > da {
                uw = da / sa;
                u0 = (1.0 - uw) / 2.0;
            } else {
                vh = sa / da;
                v0 = (1.0 - vh) / 2.0;
            }
        }
        if let Some((l, t, r, b)) = crop {
            u0 += uw * l;
            v0 += vh * t;
            uw *= (1.0 - l - r).max(0.02);
            vh *= (1.0 - t - b).max(0.02);
            dst = (
                dst.0 + dst.2 * l,
                dst.1 + dst.3 * t,
                dst.2 * (1.0 - l - r).max(0.02),
                dst.3 * (1.0 - t - b).max(0.02),
            );
        }
        let fx = |cx: f64| u0 + ((cx - dst.0) / dst.2.max(1e-6)) * uw;
        let fy = |cy: f64| v0 + ((cy - dst.1) / dst.3.max(1e-6)) * vh;
        let x0 = fx(canvas_box.0).clamp(0.0, 1.0);
        let y0 = fy(canvas_box.1).clamp(0.0, 1.0);
        let x1 = fx(canvas_box.0 + canvas_box.2).clamp(0.0, 1.0);
        let y1 = fy(canvas_box.1 + canvas_box.3).clamp(0.0, 1.0);
        ((x0), (y0), (x1 - x0).max(0.005), (y1 - y0).max(0.005))
    }
}

impl Compositor {
    /// Build a still texture directly from CPU RGBA pixels (a decoded PNG) — the
    /// deterministic path: no video decoder involved at all.
    pub fn still_put_rgba(
        &self,
        d3d: &D3d,
        key: (String, i64),
        w: u32,
        h: u32,
        rgba: &[u8],
    ) -> Result<()> {
        unsafe {
            // engine textures are BGRA — swizzle once on upload
            let mut bgra = rgba.to_vec();
            for px in bgra.chunks_exact_mut(4) {
                px.swap(0, 2);
            }
            let desc = D3D11_TEXTURE2D_DESC {
                Width: w,
                Height: h,
                MipLevels: 1,
                ArraySize: 1,
                Format: windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM,
                SampleDesc: windows::Win32::Graphics::Dxgi::Common::DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_IMMUTABLE,
                BindFlags: D3D11_BIND_SHADER_RESOURCE.0 as u32,
                CPUAccessFlags: 0,
                MiscFlags: 0,
            };
            let init = D3D11_SUBRESOURCE_DATA {
                pSysMem: bgra.as_ptr() as _,
                SysMemPitch: w * 4,
                SysMemSlicePitch: 0,
            };
            let mut tex: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, Some(&init), Some(&mut tex))?;
            let mut st = self.stills.borrow_mut();
            if st.len() >= 256 {
                // evict ONE entry — a clear-all forced every still to reload (and the
                // freeze showed a decode fallback while it did)
                if let Some(k) = st.keys().next().cloned() {
                    st.remove(&k);
                }
            }
            st.insert(key, (tex.unwrap(), (w, h)));
            Ok(())
        }
    }

    pub fn still_get(&self, key: &(String, i64)) -> Option<(ID3D11Texture2D, (u32, u32))> {
        self.stills.borrow().get(key).cloned()
    }

    pub fn caption_get(&self, key: &str) -> Option<CaptionTex> {
        self.caption_stills.borrow().get(key).cloned()
    }

    pub fn caption_get_for_clip(&self, clip_id: &str) -> Option<CaptionTex> {
        let key = self.caption_by_clip.borrow().get(clip_id).cloned()?;
        self.caption_get(&key)
    }

    pub fn caption_put_rgba(
        &self,
        d3d: &D3d,
        key: String,
        clip_id: &str,
        w: u32,
        h: u32,
        rgba: &[u8],
        dst: (f64, f64, f64, f64),
        font_size: f64,
    ) -> Result<()> {
        unsafe {
            let mut bgra = rgba.to_vec();
            for px in bgra.chunks_exact_mut(4) {
                px.swap(0, 2);
            }
            let desc = D3D11_TEXTURE2D_DESC {
                Width: w,
                Height: h,
                MipLevels: 1,
                ArraySize: 1,
                Format: windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM,
                SampleDesc: windows::Win32::Graphics::Dxgi::Common::DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_IMMUTABLE,
                BindFlags: D3D11_BIND_SHADER_RESOURCE.0 as u32,
                CPUAccessFlags: 0,
                MiscFlags: 0,
            };
            let init = D3D11_SUBRESOURCE_DATA {
                pSysMem: bgra.as_ptr() as _,
                SysMemPitch: w * 4,
                SysMemSlicePitch: 0,
            };
            let mut tex: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, Some(&init), Some(&mut tex))?;
            let mut caps = self.caption_stills.borrow_mut();
            if caps.len() >= 512 {
                if let Some(k) = caps.keys().next().cloned() {
                    caps.remove(&k);
                }
            }
            caps.insert(key.clone(), (tex.unwrap(), (w, h), dst, font_size));
            self.caption_by_clip.borrow_mut().insert(clip_id.to_string(), key);
            Ok(())
        }
    }

    /// Store a private copy of `tex` for a freeze frame (bounded cache).
    pub fn still_put(&self, d3d: &D3d, key: (String, i64), tex: &ID3D11Texture2D, wh: (u32, u32)) -> Result<()> {
        unsafe {
            let mut desc = D3D11_TEXTURE2D_DESC::default();
            tex.GetDesc(&mut desc);
            desc.BindFlags = D3D11_BIND_SHADER_RESOURCE.0 as u32;
            desc.Usage = D3D11_USAGE_DEFAULT;
            desc.CPUAccessFlags = 0;
            desc.MiscFlags = 0;
            let mut copy: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, None, Some(&mut copy))?;
            let copy = copy.unwrap();
            d3d.ctx.CopyResource(&copy, tex);
            let mut st = self.stills.borrow_mut();
            if st.len() >= 256 {
                if let Some(k) = st.keys().next().cloned() {
                    st.remove(&k);
                }
            }
            st.insert(key, (copy, wh));
        }
        Ok(())
    }

    pub fn readback(&mut self, d3d: &D3d) -> Result<()> {
        self.readback_inner(d3d, false)
    }

    /// SYNCHRONOUS readback: maps the frame just composed (one GPU sync, ~5-20ms).
    /// For INTERACTIVE one-shot frames (click/seek/scrub-settle/cache fill) — the
    /// double-buffered variant returns the PREVIOUS compose, which on a playhead jump
    /// flashed the OLD position for a beat before the new frame arrived.
    pub fn readback_sync(&mut self, d3d: &D3d) -> Result<()> {
        self.readback_inner(d3d, true)
    }

    fn readback_inner(&mut self, d3d: &D3d, sync: bool) -> Result<()> {
        unsafe {
            let cur = self.staging_i;
            d3d.ctx.CopyResource(&self.staging[cur], &self.canvas);
            let n = self.staging.len();
            let map_src = if sync {
                cur
            } else {
                // During warm-up, map the just-copied texture so the preview is never
                // blank. Once all staging textures have content, map the oldest frame.
                if self.staging_filled + 1 >= n {
                    (cur + 1) % n
                } else {
                    cur
                }
            };
            self.staging_i = (cur + 1) % n;
            self.staging_filled = (self.staging_filled + 1).min(n);
            let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
            d3d.ctx.Map(&self.staging[map_src], 0, D3D11_MAP_READ, 0, Some(&mut mapped))?;
            let pitch = mapped.RowPitch as usize;
            let src = mapped.pData as *const u8;
            let (w, h) = (self.width as usize, self.height as usize);
            for y in 0..h {
                let row = std::slice::from_raw_parts(src.add(y * pitch), w * 4);
                let out = &mut self.rgba[y * w * 4..(y + 1) * w * 4];
                for x in 0..w {
                    out[x * 4] = row[x * 4 + 2];
                    out[x * 4 + 1] = row[x * 4 + 1];
                    out[x * 4 + 2] = row[x * 4];
                    out[x * 4 + 3] = 255;
                }
            }
            d3d.ctx.Unmap(&self.staging[map_src], 0);
            Ok(())
        }
    }
}
