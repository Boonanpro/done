//! M0 gate #1 — the frame-server heart: hardware-decoded random access to REAL footage.
//!
//! Opens a video with a Media Foundation Source Reader bound to a D3D11 device
//! (DXVA/NVDEC — the same silicon path Filmora uses), then measures what an NLE
//! actually needs:
//!   1. sequential decode throughput (play speed headroom)
//!   2. ACCURATE random-seek latency (scrub feel): seek + decode-to-target, stats over N seeks
//!   3. dumps a decoded frame as BMP for eyeball proof
//!
//! Usage: m0_decode <video path> [seeks N]

use std::time::Instant;

use anyhow::{bail, Result};
use windows::core::{Interface, GUID, PCWSTR};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::DXGI_FORMAT_NV12;
use windows::Win32::Media::MediaFoundation::*;
use windows::core::PROPVARIANT;
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};

const HNS: i64 = 10_000_000; // 100ns units per second

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

struct FrameServer {
    reader: IMFSourceReader,
    device: ID3D11Device,
    duration_s: f64,
    width: u32,
    height: u32,
}

impl FrameServer {
    fn open(path: &str) -> Result<Self> {
        unsafe {
            // D3D11 device with video + multithread protection (decoder runs on MF threads)
            let mut device: Option<ID3D11Device> = None;
            D3D11CreateDevice(
                None,
                D3D_DRIVER_TYPE_HARDWARE,
                None,
                D3D11_CREATE_DEVICE_VIDEO_SUPPORT | D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                None,
                D3D11_SDK_VERSION,
                Some(&mut device),
                None,
                None,
            )?;
            let device = device.unwrap();
            let mt: ID3D11Multithread = device.cast()?;
            let _ = mt.SetMultithreadProtected(true);

            let mut reset_token = 0u32;
            let mut mgr: Option<IMFDXGIDeviceManager> = None;
            MFCreateDXGIDeviceManager(&mut reset_token, &mut mgr)?;
            let mgr = mgr.unwrap();
            mgr.ResetDevice(&device, reset_token)?;

            let mut attrs: Option<IMFAttributes> = None;
            MFCreateAttributes(&mut attrs, 4)?;
            let attrs = attrs.unwrap();
            attrs.SetUnknown(&MF_SOURCE_READER_D3D_MANAGER, &mgr)?;
            attrs.SetUINT32(&MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1)?;
            attrs.SetUINT32(&MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, 1)?;

            let w = wide(path);
            let reader = MFCreateSourceReaderFromURL(PCWSTR(w.as_ptr()), &attrs)?;

            // video stream only, decoded to NV12 (stays on the GPU as D3D11 textures)
            let out_type = MFCreateMediaType()?;
            out_type.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            out_type.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_NV12)?;
            reader.SetCurrentMediaType(
                MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32,
                None,
                &out_type,
            )?;
            let _ = reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false);
            reader.SetStreamSelection(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32, true)?;

            // duration + frame size
            let pv = reader.GetPresentationAttribute(
                MF_SOURCE_READER_MEDIASOURCE.0 as u32,
                &MF_PD_DURATION,
            )?;
            let dur_hns = pv.as_raw().Anonymous.Anonymous.Anonymous.hVal;
            let cur = reader.GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32)?;
            let sz = cur.GetUINT64(&MF_MT_FRAME_SIZE)?;
            let (width, height) = ((sz >> 32) as u32, (sz & 0xffff_ffff) as u32);

            Ok(Self {
                reader,
                device,
                duration_s: dur_hns as f64 / HNS as f64,
                width,
                height,
            })
        }
    }

    /// Read the next decoded sample; returns (pts_seconds, sample).
    fn next_sample(&self) -> Result<Option<(f64, IMFSample)>> {
        unsafe {
            let mut flags = 0u32;
            let mut sample: Option<IMFSample> = None;
            let mut pts: i64 = 0;
            self.reader.ReadSample(
                MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32,
                0,
                None,
                Some(&mut flags),
                Some(&mut pts),
                Some(&mut sample),
            )?;
            if flags & MF_SOURCE_READERF_ENDOFSTREAM.0 as u32 != 0 {
                return Ok(None);
            }
            match sample {
                Some(s) => Ok(Some((pts as f64 / HNS as f64, s))),
                None => Ok(None),
            }
        }
    }

    /// ACCURATE seek: position at t, then decode forward until pts >= t (what a scrub shows).
    fn frame_at(&self, t: f64) -> Result<Option<(f64, IMFSample)>> {
        unsafe {
            let pv = PROPVARIANT::from((t * HNS as f64) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        loop {
            match self.next_sample()? {
                Some((pts, s)) => {
                    if pts + 0.0005 >= t {
                        return Ok(Some((pts, s)));
                    }
                }
                None => return Ok(None),
            }
        }
    }
}

/// Save an NV12 D3D11 texture (from an IMFSample) as a BMP — eyeball proof, zero extra deps.
fn dump_bmp(fs: &FrameServer, sample: &IMFSample, out: &str) -> Result<()> {
    unsafe {
        let buf = sample.GetBufferByIndex(0)?;
        let dxgi: IMFDXGIBuffer = buf.cast()?;
        let mut tex_ptr: *mut core::ffi::c_void = core::ptr::null_mut();
        dxgi.GetResource(&ID3D11Texture2D::IID, &mut tex_ptr)?;
        let tex = ID3D11Texture2D::from_raw(tex_ptr);
        let sub = dxgi.GetSubresourceIndex().unwrap_or(0);

        let mut desc = D3D11_TEXTURE2D_DESC::default();
        tex.GetDesc(&mut desc);
        let (w, h) = (fs.width, fs.height);
        let staging_desc = D3D11_TEXTURE2D_DESC {
            Width: desc.Width,
            Height: desc.Height,
            MipLevels: 1,
            ArraySize: 1,
            Format: DXGI_FORMAT_NV12,
            SampleDesc: desc.SampleDesc,
            Usage: D3D11_USAGE_STAGING,
            BindFlags: 0,
            CPUAccessFlags: D3D11_CPU_ACCESS_READ.0 as u32,
            MiscFlags: 0,
        };
        let mut staging: Option<ID3D11Texture2D> = None;
        fs.device.CreateTexture2D(&staging_desc, None, Some(&mut staging))?;
        let staging = staging.unwrap();
        let ctx = fs.device.GetImmediateContext()?;
        ctx.CopySubresourceRegion(&staging, 0, 0, 0, 0, &tex, sub, None);
        let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
        ctx.Map(&staging, 0, D3D11_MAP_READ, 0, Some(&mut mapped))?;

        let pitch = mapped.RowPitch as usize;
        let base = mapped.pData as *const u8;
        let y_plane = std::slice::from_raw_parts(base, pitch * desc.Height as usize);
        let uv_off = pitch * desc.Height as usize;
        let uv_plane = std::slice::from_raw_parts(base.add(uv_off), pitch * (desc.Height as usize / 2));

        // NV12 -> BGR (BT.709) + BMP write
        let (ow, oh) = (w as usize, h as usize);
        let row_bytes = (ow * 3 + 3) & !3;
        let mut bmp = vec![0u8; 54 + row_bytes * oh];
        let fsz = bmp.len() as u32;
        bmp[0] = b'B'; bmp[1] = b'M';
        bmp[2..6].copy_from_slice(&fsz.to_le_bytes());
        bmp[10..14].copy_from_slice(&54u32.to_le_bytes());
        bmp[14..18].copy_from_slice(&40u32.to_le_bytes());
        bmp[18..22].copy_from_slice(&(ow as i32).to_le_bytes());
        bmp[22..26].copy_from_slice(&(oh as i32).to_le_bytes());
        bmp[26..28].copy_from_slice(&1u16.to_le_bytes());
        bmp[28..30].copy_from_slice(&24u16.to_le_bytes());
        for y in 0..oh {
            for x in 0..ow {
                let yy = y_plane[y * pitch + x] as f32;
                let u = uv_plane[(y / 2) * pitch + (x & !1)] as f32 - 128.0;
                let v = uv_plane[(y / 2) * pitch + (x & !1) + 1] as f32 - 128.0;
                let c = (yy - 16.0) * 1.164;
                let r = (c + 1.793 * v).clamp(0.0, 255.0) as u8;
                let g = (c - 0.213 * u - 0.533 * v).clamp(0.0, 255.0) as u8;
                let b = (c + 2.112 * u).clamp(0.0, 255.0) as u8;
                let o = 54 + (oh - 1 - y) * row_bytes + x * 3;
                bmp[o] = b; bmp[o + 1] = g; bmp[o + 2] = r;
            }
        }
        ctx.Unmap(&staging, 0);
        std::fs::write(out, &bmp)?;
    }
    Ok(())
}

fn stats(mut v: Vec<f64>) -> (f64, f64, f64, f64) {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    (v[0], v[n / 2], v[((n as f64 * 0.95) as usize).min(n - 1)], v[n - 1])
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        bail!("usage: m0_decode <video> [seeks]");
    }
    let n_seeks: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(100);

    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        MFStartup(MF_VERSION, MFSTARTUP_FULL)?;
    }

    let t0 = Instant::now();
    let fs = FrameServer::open(&args[1])?;
    println!(
        "open: {:.0}ms  {}x{}  dur={:.1}s",
        t0.elapsed().as_secs_f64() * 1000.0,
        fs.width,
        fs.height,
        fs.duration_s
    );

    // 1) sequential decode throughput (300 frames from t=1s)
    let _ = fs.frame_at(1.0)?;
    let t = Instant::now();
    let mut n = 0;
    while n < 300 {
        match fs.next_sample()? {
            Some(_) => n += 1,
            None => break,
        }
    }
    let el = t.elapsed().as_secs_f64();
    println!("sequential: {} frames in {:.2}s = {:.0} fps", n, el, n as f64 / el);

    // 2) accurate random seeks across the file — the scrub-feel number
    let mut lat = Vec::new();
    let mut rng: u64 = 0x9E3779B97F4A7C15;
    for _ in 0..n_seeks {
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        let t_target = (rng % 1000) as f64 / 1000.0 * (fs.duration_s - 1.0).max(0.1);
        let t = Instant::now();
        let got = fs.frame_at(t_target)?;
        let ms = t.elapsed().as_secs_f64() * 1000.0;
        if got.is_some() {
            lat.push(ms);
        }
    }
    let (mn, med, p95, mx) = stats(lat.clone());
    println!(
        "random accurate seek x{}: min={:.0}ms median={:.0}ms p95={:.0}ms max={:.0}ms",
        lat.len(), mn, med, p95, mx
    );

    // 3) eyeball proof
    if let Some((pts, s)) = fs.frame_at(fs.duration_s * 0.5)? {
        let out = format!("{}.m0.bmp", args[1]);
        dump_bmp(&fs, &s, &out)?;
        println!("frame@{pts:.2}s dumped -> {out}");
    }
    println!("M0 DECODE OK");
    Ok(())
}
