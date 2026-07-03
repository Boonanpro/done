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

const HLSL: &str = r#"
cbuffer CB : register(b0) { float4 dst; float4 uvr; float4 aff; };
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
  return float4(c.rgb, 1.0);
}
float4 ps_popout(VOut i) : SV_Target {
  float3 c = tex0.Sample(smp, i.uv).rgb;
  float a = tex1.Sample(smp, i.uv).r;
  return float4(c * a, a);
}
// LIVE pop-out: color from the ORIGINAL frame (t0, full frame rate — the lips), person
// alpha (t1) + contact-shadow base (t2) from the baked matte twin, card geometry from the
// static mask texture (t3: R=rounded card, G=rim band, B=drop shadow). The 5 composite
// steps are popout_overlay.py's, evaluated per pixel. uv = bake canvas space;
// aff = (src0.xy, srcsize.zw) maps canvas uv -> original uv.
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
  // 4. contact shadow cast by the popped head onto the card
  float shm = shb * ca * (1 - pa) * 0.5;
  rgb *= (1 - shm);
  // 5. person on top; premultiplied out
  float nna = outa + pa * (1 - outa);
  rgb = (rgb * outa * (1 - pa) + src * pa) / max(nna, 1e-6);
  return float4(rgb * nna, nna);
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
}

pub struct Compositor {
    pub width: u32,
    pub height: u32,
    canvas: ID3D11Texture2D,
    rtv: ID3D11RenderTargetView,
    staging: [ID3D11Texture2D; 2],
    staging_i: usize,
    staging_warm: bool,
    vs: ID3D11VertexShader,
    ps_plain: ID3D11PixelShader,
    ps_popout: ID3D11PixelShader,
    ps_popout_live: ID3D11PixelShader,
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

            let vsb = compile("vs", "vs_5_0")?;
            let psb1 = compile("ps_plain", "ps_5_0")?;
            let psb2 = compile("ps_popout", "ps_5_0")?;
            let psb3 = compile("ps_popout_live", "ps_5_0")?;
            let bytes = |b: &ID3DBlob| std::slice::from_raw_parts(b.GetBufferPointer() as *const u8, b.GetBufferSize());
            let mut vs: Option<ID3D11VertexShader> = None;
            d3d.device.CreateVertexShader(bytes(&vsb), None, Some(&mut vs))?;
            let mut ps_plain: Option<ID3D11PixelShader> = None;
            d3d.device.CreatePixelShader(bytes(&psb1), None, Some(&mut ps_plain))?;
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
                staging: [staging0.unwrap(), staging1.unwrap()],
                staging_i: 0,
                staging_warm: false,
                vs: vs.unwrap(),
                ps_plain: ps_plain.unwrap(),
                ps_popout: ps_popout.unwrap(),
                ps_popout_live: ps_popout_live.unwrap(),
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

    /// Draw `tex` into dest box (canvas fractions). cover=true crops source to box aspect.
    /// `matte` switches to the pop-out shader (alpha from matte luma).
    pub fn draw(
        &self,
        d3d: &D3d,
        tex: &ID3D11Texture2D,
        src_wh: (u32, u32),
        dst: (f64, f64, f64, f64),
        cover: bool,
        matte: Option<&ID3D11Texture2D>,
    ) -> Result<()> {
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
            let cbv = Cb {
                dst: [dst.0 as f32, dst.1 as f32, dst.2 as f32, dst.3 as f32],
                uvr: [u0, v0, uw, vh],
                aff: [0.0, 0.0, 1.0, 1.0],
            };
            d3d.ctx.UpdateSubresource(&self.cb, 0, None, &cbv as *const _ as _, 0, 0);
            d3d.ctx.PSSetShaderResources(0, Some(&views));
            d3d.ctx
                .PSSetShader(if matte.is_some() { &self.ps_popout } else { &self.ps_plain }, None);
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

    /// Read the canvas back as RGBA — DOUBLE-BUFFERED: copy into staging[i], map
    /// staging[i-1] (last frame). Mapping the just-copied one stalls on the whole in-flight
    /// GPU frame (measured 30-85ms); mapping the previous is a pure memcpy for +1 frame of
    /// preview latency.
    pub fn readback(&mut self, d3d: &D3d) -> Result<()> {
        unsafe {
            let cur = self.staging_i;
            let prev = 1 - cur;
            d3d.ctx.CopyResource(&self.staging[cur], &self.canvas);
            self.staging_i = prev;
            let map_src = if self.staging_warm {
                prev
            } else {
                // first frame: map the JUST-copied staging synchronously (one-time GPU
                // sync) — returning empty here left the paused preview black until the
                // second user interaction
                self.staging_warm = true;
                cur
            };
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
