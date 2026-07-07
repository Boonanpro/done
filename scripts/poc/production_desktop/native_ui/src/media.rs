//! Media layer — the M0 frame server grown into a pooled, multi-stream engine.
//! Pull-based: `frame_bgra(path, stream, t)` returns a BGRA D3D11 texture for the newest
//! frame at t (decode-ahead within a clip, accurate-seek on jumps). Audio is a WASAPI
//! shared-mode render fed per-clip; its position is the MASTER clock during playback.

use std::collections::{HashMap, VecDeque};

use anyhow::Result;
use windows::core::{Interface, GUID, PCWSTR, PROPVARIANT};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::*;
use windows::Win32::Media::Audio::*;
use windows::Win32::Media::MediaFoundation::*;
use windows::Win32::System::Com::*;

pub const HNS: f64 = 10_000_000.0;

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

pub struct D3d {
    pub device: ID3D11Device,
    pub ctx: ID3D11DeviceContext,
    pub mgr: IMFDXGIDeviceManager,
    pub vdev: ID3D11VideoDevice,
    pub vctx: ID3D11VideoContext,
}

impl D3d {
    pub fn new() -> Result<Self> {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            MFStartup(MF_VERSION, MFSTARTUP_FULL)?;
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
            let mut token = 0u32;
            let mut mgr: Option<IMFDXGIDeviceManager> = None;
            MFCreateDXGIDeviceManager(&mut token, &mut mgr)?;
            let mgr = mgr.unwrap();
            mgr.ResetDevice(&device, token)?;
            let ctx = device.GetImmediateContext()?;
            let vdev: ID3D11VideoDevice = device.cast()?;
            let vctx: ID3D11VideoContext = ctx.cast()?;
            Ok(Self { device, ctx, mgr, vdev, vctx })
        }
    }
}

/// One decoded video stream of one file: NV12 via HW decode, converted to an owned BGRA
/// texture with a per-source VideoProcessor. Keeps a 1-frame lookahead + last position.
pub struct VideoStream {
    pub name: String,
    reader: IMFSourceReader,
    stream: u32,
    pub width: u32,
    pub height: u32,
    pending: Option<(f64, IMFSample)>,
    last_pts: f64,
    last_req: f64,
    prime_target: Option<f64>,
    dur: f64,      // container duration — requests past it freeze on the last frame
    pub eos: bool, // reader returned ENDOFSTREAM; cleared by seek
    // NV12 -> BGRA converter
    vp: ID3D11VideoProcessor,
    vp_enum: ID3D11VideoProcessorEnumerator,
    pub bgra: ID3D11Texture2D,
    out_view: ID3D11VideoProcessorOutputView,
    has_frame: bool,
}

impl VideoStream {
    pub fn open(d3d: &D3d, path: &str, stream: u32, full_range: bool) -> Result<Self> {
        unsafe {
            let mut attrs: Option<IMFAttributes> = None;
            MFCreateAttributes(&mut attrs, 4)?;
            let attrs = attrs.unwrap();
            attrs.SetUnknown(&MF_SOURCE_READER_D3D_MANAGER, &d3d.mgr)?;
            attrs.SetUINT32(&MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1)?;
            // NO ENABLE_ADVANCED_VIDEO_PROCESSING: we output native NV12 and convert with
            // our own VideoProcessor — the reader-internal VP MFT only made every seek
            // flush ~5x more expensive (55ms -> ~300ms on the 4K originals)
            // scrub responsiveness: without this the reader queues frames ahead internally
            // and every SetCurrentPosition pays a long flush (~100ms+ on 4K long-GOP)
            attrs.SetUINT32(&MF_LOW_LATENCY, 1)?;
            let wp = wide(path);
            let reader = MFCreateSourceReaderFromURL(PCWSTR(wp.as_ptr()), &attrs)?;
            // `stream` = Nth VIDEO track; resolve to the actual MF stream index (stream 0 of a
            // normal mp4 is often the AUDIO track — raw indices are meaningless).
            let stream_ordinal = stream;
            let stream = {
                let mut idx = 0u32;
                let mut seen = 0u32;
                loop {
                    let Ok(nt) = reader.GetNativeMediaType(idx, 0) else {
                        return Err(anyhow::anyhow!("no video track #{stream} in {path}"));
                    };
                    if nt.GetGUID(&MF_MT_MAJOR_TYPE)? == MFMediaType_Video {
                        if seen == stream {
                            break idx;
                        }
                        seen += 1;
                    }
                    idx += 1;
                }
            };
            let ty = MFCreateMediaType()?;
            ty.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            ty.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_NV12)?;
            reader.SetCurrentMediaType(stream, None, &ty)?;
            let _ = reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false);
            reader.SetStreamSelection(stream, true)?;
            let cur = reader.GetCurrentMediaType(stream)?;
            let sz = cur.GetUINT64(&MF_MT_FRAME_SIZE)?;
            let (src_w, src_h) = ((sz >> 32) as u32, (sz & 0xffff_ffff) as u32);
            // MF does NOT auto-rotate; honor the rotation metadata via the VideoProcessor and
            // swap the destination dims for 90/270 so downstream sees an upright frame.
            let rotation = cur.GetUINT32(&MF_MT_VIDEO_ROTATION).unwrap_or(0) % 360;
            let (width, height) = if rotation == 90 || rotation == 270 { (src_h, src_w) } else { (src_w, src_h) };

            // BGRA destination + VideoProcessor
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
            let mut bgra: Option<ID3D11Texture2D> = None;
            d3d.device.CreateTexture2D(&desc, None, Some(&mut bgra))?;
            let bgra = bgra.unwrap();
            let vp_enum = d3d.vdev.CreateVideoProcessorEnumerator(&D3D11_VIDEO_PROCESSOR_CONTENT_DESC {
                InputFrameFormat: D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE,
                InputFrameRate: DXGI_RATIONAL { Numerator: 30, Denominator: 1 },
                InputWidth: src_w,
                InputHeight: src_h,
                OutputFrameRate: DXGI_RATIONAL { Numerator: 30, Denominator: 1 },
                OutputWidth: width,
                OutputHeight: height,
                Usage: D3D11_VIDEO_USAGE_PLAYBACK_NORMAL,
            })?;
            let vp = d3d.vdev.CreateVideoProcessor(&vp_enum, 0)?;
            // Explicit color spaces — the defaults produce LIMITED-range RGB (black=16), which
            // shows up as a gray veil over the frame and a 6% "ghost" where a matte should be
            // fully transparent. Input: BT.709; the matte track (video ordinal 1) is FULL range
            // (the bake encodes alpha pc), color tracks are studio range. Output: full-range RGB.
            // D3D11_VIDEO_PROCESSOR_COLOR_SPACE bitfield: Usage:1|RGB_Range:1|YCbCr_Matrix:1|
            // YCbCr_xvYCC:1|Nominal_Range:2 → 709 matrix = bit2, nominal 16_235=0x10 / 0_255=0x20.
            let cs_in = D3D11_VIDEO_PROCESSOR_COLOR_SPACE {
                _bitfield: 0x4 | if full_range { 0x20 } else { 0x10 },
            };
            let cs_out = D3D11_VIDEO_PROCESSOR_COLOR_SPACE { _bitfield: 0 };
            d3d.vctx.VideoProcessorSetStreamColorSpace(&vp, 0, &cs_in);
            d3d.vctx.VideoProcessorSetOutputColorSpace(&vp, &cs_out);
            if rotation != 0 {
                let r = match rotation {
                    90 => D3D11_VIDEO_PROCESSOR_ROTATION_90,
                    180 => D3D11_VIDEO_PROCESSOR_ROTATION_180,
                    _ => D3D11_VIDEO_PROCESSOR_ROTATION_270,
                };
                d3d.vctx.VideoProcessorSetStreamRotation(&vp, 0, true, r);
            }
            // SOURCE RECT = the DISPLAY area of the decoder surface. Without it the VP
            // samples the codec's alignment padding too (a 1080-wide proxy decodes on a
            // 1088-wide surface): the picture squeezed ~0.7% and 8 junk columns landed on
            // the right edge — measured as the play(proxy)/pause(original) width breathing.
            d3d.vctx.VideoProcessorSetStreamSourceRect(
                &vp,
                0,
                true,
                Some(&windows::Win32::Foundation::RECT {
                    left: 0,
                    top: 0,
                    right: src_w as i32,
                    bottom: src_h as i32,
                }),
            );
            let mut ov: Option<ID3D11VideoProcessorOutputView> = None;
            d3d.vdev.CreateVideoProcessorOutputView(
                &bgra,
                &vp_enum,
                &D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC {
                    ViewDimension: D3D11_VPOV_DIMENSION_TEXTURE2D,
                    Anonymous: D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC_0 {
                        Texture2D: D3D11_TEX2D_VPOV { MipSlice: 0 },
                    },
                },
                Some(&mut ov),
            )?;
            let dur = reader
                .GetPresentationAttribute(MF_SOURCE_READER_MEDIASOURCE.0 as u32, &MF_PD_DURATION)
                .map(|pv| pv.as_raw().Anonymous.Anonymous.Anonymous.hVal as f64 / HNS)
                .unwrap_or(f64::MAX);
            Ok(Self {
                name: format!("{}#{}", path.rsplit('/').next().unwrap_or(path), stream),
                reader,
                stream,
                width,
                height,
                pending: None,
                last_pts: -1.0,
                last_req: -1.0,
                prime_target: None,
                dur,
                eos: false,
                vp,
                vp_enum,
                bgra,
                out_view: ov.unwrap(),
                has_frame: false,
            })
        }
    }

    fn read_next(&mut self) -> Result<Option<(f64, IMFSample)>> {
        unsafe {
            let mut flags = 0u32;
            let mut sample: Option<IMFSample> = None;
            let mut pts = 0i64;
            self.reader
                .ReadSample(self.stream, 0, None, Some(&mut flags), Some(&mut pts), Some(&mut sample))?;
            if flags & MF_SOURCE_READERF_ENDOFSTREAM.0 as u32 != 0 {
                self.eos = true;
                return Ok(None);
            }
            Ok(sample.map(|s| (pts as f64 / HNS, s)))
        }
    }

    /// Clamp a requested source time into the file (seeking past the end raises
    /// 0xC00D36E5 and clip in/out points routinely overshoot the baked file by a frame).
    fn clamp_t(&self, t: f64) -> f64 {
        t.min(self.dur - 0.01).max(0.0)
    }

    fn seek(&mut self, t: f64) -> Result<()> {
        let t = self.clamp_t(t);
        unsafe {
            let pv = PROPVARIANT::from((t * HNS) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        self.eos = false;
        self.pending = None;
        let mut prev: Option<(f64, IMFSample)> = None;
        while let Some((pts, s)) = self.read_next()? {
            if pts + 0.0005 >= t {
                if pts > t + 0.2 {
                    if let Some(p) = prev.take() {
                        self.pending = Some(p); // VFR hold: show the pre-gap frame
                        // the future frame is re-fetched on the next advance
                        break;
                    }
                }
                self.pending = Some((pts, s));
                break;
            }
            prev = Some((pts, s));
        }
        Ok(())
    }

    fn blit(&mut self, d3d: &D3d, sample: &IMFSample) -> Result<()> {
        unsafe {
            let buf = sample.GetBufferByIndex(0)?;
            let dxgi: IMFDXGIBuffer = buf.cast()?;
            let mut texp: *mut core::ffi::c_void = core::ptr::null_mut();
            dxgi.GetResource(&ID3D11Texture2D::IID, &mut texp)?;
            let tex = ID3D11Texture2D::from_raw(texp);
            let sub = dxgi.GetSubresourceIndex().unwrap_or(0);
            let mut iv: Option<ID3D11VideoProcessorInputView> = None;
            d3d.vdev.CreateVideoProcessorInputView(
                &tex,
                &self.vp_enum,
                &D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC {
                    FourCC: 0,
                    ViewDimension: D3D11_VPIV_DIMENSION_TEXTURE2D,
                    Anonymous: D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC_0 {
                        Texture2D: D3D11_TEX2D_VPIV { MipSlice: 0, ArraySlice: sub },
                    },
                },
                Some(&mut iv),
            )?;
            let mut stream = D3D11_VIDEO_PROCESSOR_STREAM {
                Enable: true.into(),
                pInputSurface: std::mem::ManuallyDrop::new(iv),
                ..Default::default()
            };
            d3d.vctx
                .VideoProcessorBlt(&self.vp, &self.out_view, 0, std::slice::from_ref(&stream))?;
            std::mem::ManuallyDrop::drop(&mut stream.pInputSurface);
            self.has_frame = true;
            Ok(())
        }
    }

    pub fn pending_pts(&self) -> Option<f64> {
        self.pending.as_ref().map(|(p, _)| *p)
    }

    /// Incremental prime: advance the decoder TOWARD src_t a couple of frames per call and
    /// return true when positioned. A full accurate seek on a 4K long-GOP original costs
    /// ~200ms — running that synchronously on the media thread froze video AND starved the
    /// audio buffer (the "stutter moved earlier + audio breaks" bug). Sliced, it costs
    /// ≤~12ms per loop iteration.
    pub fn prime_step(&mut self, src_t: f64) -> Result<bool> {
        let src_t = self.clamp_t(src_t);
        if self.eos && self.pending.is_none() && src_t >= self.last_pts {
            self.prime_target = None;
            return Ok(true); // nothing beyond the end to position at
        }
        let positioned = self
            .pending_pts()
            .map(|p| (p - src_t).abs() < 0.4)
            .unwrap_or(false)
            || (self.last_pts >= 0.0 && (self.last_pts - src_t).abs() < 0.4);
        if positioned {
            self.prime_target = None;
            return Ok(true);
        }
        if self.prime_target.map(|pt| (pt - src_t).abs() > 0.05).unwrap_or(true) {
            unsafe {
                let pv = PROPVARIANT::from((src_t * HNS) as i64);
                self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
            }
            self.eos = false;
            self.prime_target = Some(src_t);
            self.pending = None;
        }
        for _ in 0..1 {
            match self.read_next()? {
                Some((pts, sm)) => {
                    if pts + 0.0005 >= src_t {
                        self.pending = Some((pts, sm));
                        self.prime_target = None;
                        return Ok(true);
                    }
                }
                None => {
                    self.prime_target = None;
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }

    /// Lookahead: position the decoder AT src_t without touching the last shown frame.
    /// No-op if already there (or within the decode-ahead window).
    pub fn prime(&mut self, _d3d: &D3d, src_t: f64) -> Result<()> {
        if let Some((pts, _)) = &self.pending {
            if (*pts - src_t).abs() < 0.4 {
                return Ok(());
            }
        }
        if (self.last_pts - src_t).abs() < 0.4 {
            return Ok(());
        }
        self.seek(src_t)
    }

    /// SCRUB frame: put something honest on screen within ~budget_ms. Walks the GOP toward
    /// the exact frame only while the budget lasts, then shows the newest frame reached
    /// (nearest keyframe on long-GOP sources — the Filmora fast-drag look). Returns true
    /// when the EXACT frame for t is on screen; false = budget ran out mid-walk, call
    /// again (same t) to keep refining while the finger rests.
    pub fn ensure_frame_scrub(&mut self, d3d: &D3d, t: f64, budget_ms: f64) -> Result<bool> {
        let t = self.clamp_t(t);
        self.prime_target = None;
        self.last_req = t;
        if self.has_frame && self.last_pts >= 0.0 && (self.last_pts - t).abs() < 0.04 {
            return Ok(true); // already showing this frame
        }
        if self.eos && self.pending.is_none() && self.has_frame && t >= self.last_pts {
            return Ok(true); // past the last real frame: freeze it
        }
        let t0 = std::time::Instant::now();
        // forward within this window continues the decode (progress accumulates across
        // ticks); anything else re-seeks to the preceding keyframe. 1.2s: walking a long-GOP
        // 4K source across the timeline's cut jumps (1-3s) cost far more than a keyframe seek
        let cont = (self.last_pts >= 0.0 && t >= self.last_pts && t < self.last_pts + 1.2)
            || self.pending_pts().map(|p| t >= p && t < p + 1.2).unwrap_or(false);
        if !cont {
            unsafe {
                let pv = PROPVARIANT::from((t * HNS) as i64);
                self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
            }
            self.pending = None;
        }
        let mut newest: Option<(f64, IMFSample)> = None;
        let mut exact = true; // stays true when we stop at a future frame / EOS
        loop {
            let nx = if self.pending.is_some() { self.pending.take() } else { self.read_next()? };
            let Some((pts, s)) = nx else { break };
            if pts > t + 0.0005 {
                self.pending = Some((pts, s)); // future frame — keep for the next tick
                break;
            }
            newest = Some((pts, s));
            if t0.elapsed().as_secs_f64() * 1000.0 > budget_ms {
                exact = false; // budget spent mid-walk — show what we reached
                break;
            }
        }
        if let Some((pts, s)) = newest {
            self.blit(d3d, &s)?;
            self.last_pts = pts;
        }
        let _ = cont;
        Ok(exact && self.has_frame)
    }

    /// Ensure `bgra` holds the newest frame with pts <= t. Seeks on backward/far-forward jumps.
    pub fn ensure_frame(&mut self, d3d: &D3d, t: f64) -> Result<bool> {
        let t = self.clamp_t(t);
        if self.eos && self.pending.is_none() && self.has_frame && t >= self.last_pts {
            self.prime_target = None;
            self.last_req = t;
            return Ok(true); // past the last real frame: freeze it (NLE end-of-source)
        }
        // a prime walk toward ~t is in flight: FINISH it (decode forward) instead of
        // re-seeking — re-seek would restart the whole GOP walk from the keyframe
        if let Some(pt) = self.prime_target {
            if (pt - t).abs() < 0.6 {
                let w0 = std::time::Instant::now();
                while let Some((pts, sm)) = self.read_next()? {
                    if pts + 0.0005 >= t.min(pt) {
                        self.pending = Some((pts, sm));
                        break;
                    }
                }
                self.prime_target = None;
                let wms = w0.elapsed().as_secs_f64() * 1000.0;
                if wms > 60.0 {
                    eprintln!("PRIMEWALK {} to {:.2}: {:.0}ms", self.name, t, wms);
                }
            } else {
                self.prime_target = None;
            }
        }
        let back = self.last_req >= 0.0 && t < self.last_req - 0.05;
        let cold = self.last_pts < 0.0;
        // far-forward: BOTH the shown frame and the lookahead frame are well behind t.
        // (pending ahead of t = a VFR hold — keep the frame, don't re-seek. But pending
        // just after last_pts with t minutes ahead = a big source jump at a cut; requiring
        // pending.is_none() here made that walk EVERY frame to t — the 4.5s stall.)
        let far = t > self.last_pts + 1.5
            && self.pending_pts().map(|p| p < t - 1.5).unwrap_or(true);
        self.last_req = t;
        let jump = (back || cold || far)
            && !self.pending_pts().map(|p| (p - t).abs() < 0.6).unwrap_or(false);
        if jump {
            let _jt = std::time::Instant::now();
            let r = self.ensure_jump(d3d, t);
            let ms = _jt.elapsed().as_secs_f64() * 1000.0;
            if ms > 60.0 {
                eprintln!("JUMPSEEK {} to {:.2}: {:.0}ms", self.name, t, ms);
            }
            return r;
        }
        self.ensure_advance(d3d, t)
    }

    fn ensure_jump(&mut self, d3d: &D3d, t: f64) -> Result<bool> {
        {
            self.seek(t)?;
            // present the first frame at/after t immediately (scrub shows something NOW)
            if let Some((pts, s)) = self.pending.take() {
                self.blit(d3d, &s)?;
                self.last_pts = pts;
                self.pending = self.read_next()?;
            }
            Ok(self.has_frame)
        }
    }

    fn ensure_advance(&mut self, d3d: &D3d, t: f64) -> Result<bool> {
        let mut newest: Option<(f64, IMFSample)> = None;
        loop {
            match &self.pending {
                Some((pts, _)) if *pts <= t => {
                    newest = self.pending.take();
                    self.pending = self.read_next()?;
                }
                _ => break,
            }
        }
        if let Some((pts, s)) = newest {
            self.blit(d3d, &s)?;
            self.last_pts = pts;
        }
        Ok(self.has_frame)
    }
}

/// One-shot thumbnail: open, decode the frame at `t`, return (w, h, RGBA) downscaled.
pub fn thumbnail(d3d: &D3d, path: &str, t: f64, max_w: usize) -> Result<(usize, usize, Vec<u8>)> {
    let mut vs = VideoStream::open(d3d, path, 0, false)?;
    vs.ensure_frame(d3d, t)?;
    unsafe {
        let mut desc = D3D11_TEXTURE2D_DESC::default();
        vs.bgra.GetDesc(&mut desc);
        let sdesc = D3D11_TEXTURE2D_DESC {
            Usage: D3D11_USAGE_STAGING,
            BindFlags: 0,
            CPUAccessFlags: D3D11_CPU_ACCESS_READ.0 as u32,
            MiscFlags: 0,
            ..desc
        };
        let mut st: Option<ID3D11Texture2D> = None;
        d3d.device.CreateTexture2D(&sdesc, None, Some(&mut st))?;
        let st = st.unwrap();
        d3d.ctx.CopyResource(&st, &vs.bgra);
        let mut m = D3D11_MAPPED_SUBRESOURCE::default();
        d3d.ctx.Map(&st, 0, D3D11_MAP_READ, 0, Some(&mut m))?;
        let (w, h) = (desc.Width as usize, desc.Height as usize);
        let ow = max_w.min(w);
        let oh = (h * ow / w).max(1);
        let pitch = m.RowPitch as usize;
        let base = m.pData as *const u8;
        let mut out = vec![0u8; ow * oh * 4];
        for y in 0..oh {
            let sy = y * h / oh;
            let row = std::slice::from_raw_parts(base.add(sy * pitch), w * 4);
            for x in 0..ow {
                let sx = x * w / ow;
                let o = (y * ow + x) * 4;
                out[o] = row[sx * 4 + 2];
                out[o + 1] = row[sx * 4 + 1];
                out[o + 2] = row[sx * 4];
                out[o + 3] = 255;
            }
        }
        d3d.ctx.Unmap(&st, 0);
        Ok((ow, oh, out))
    }
}

/// Incremental audio-peak scan (waveforms): call step() repeatedly; each call decodes a
/// slice so playback requests never wait long.
pub struct PeakScan {
    dec: AudioDecoder,
    rate: u32,
    ch: usize,
    bucket: usize,
    pub peaks: Vec<f32>,
    cur: f32,
    fill: usize,
    pub done: bool,
}

impl PeakScan {
    pub fn new(path: &str) -> Result<Self> {
        let (rate, ch) = (48000u32, 2usize);
        Ok(Self {
            dec: AudioDecoder::open(path, rate, ch)?,
            rate,
            ch,
            bucket: 48000usize / 50 * 2, // 20ms * stereo
            peaks: Vec::new(),
            cur: 0.0,
            fill: 0,
            done: false,
        })
    }
    pub fn step(&mut self) -> Result<()> {
        for _ in 0..24 {
            if self.dec.eos {
                if self.fill > 0 {
                    self.peaks.push(self.cur);
                }
                self.done = true;
                return Ok(());
            }
            self.dec.pump(self.rate, self.ch)?;
            while !self.dec.fifo.is_empty() {
                let n = self.dec.fifo.len().min(self.bucket - self.fill);
                for v in self.dec.fifo.drain(..n) {
                    let a = v.abs();
                    if a > self.cur {
                        self.cur = a;
                    }
                }
                self.fill += n;
                if self.fill >= self.bucket {
                    self.peaks.push(self.cur);
                    self.cur = 0.0;
                    self.fill = 0;
                }
            }
        }
        Ok(())
    }
    /// seconds per peak bucket
    pub fn spb(&self) -> f64 {
        self.bucket as f64 / self.ch as f64 / self.rate as f64
    }
}

/// Ping-pong pool: up to TWO decoder instances per (path, stream). Dan's timelines are
/// mostly the SAME file chopped into consecutive cuts, so a boundary is a source-time jump
/// inside one file — with a single decoder that jump forces an accurate seek (~200ms on a
/// 4K long-GOP original) exactly ON the cut. The spare instance gets primed at the NEXT
/// cut's in-point ahead of time; at the boundary we just switch instances.
struct Slot {
    vs: VideoStream,
    used_frame: u64,
    touch: u64, // last frame_no this slot was used OR primed — LRU eviction key
    touched_at: std::time::Instant, // wall-clock twin of `touch` (Olive: idle-time eviction)
}

pub struct VideoPool {
    slots: HashMap<(String, u32), Vec<Slot>>,
    pub frame_no: u64,
}

impl VideoPool {
    pub fn new() -> Self {
        Self { slots: HashMap::new(), frame_no: 0 }
    }

    /// Best instance for showing src_t NOW: prefer one already positioned (continuing or
    /// primed near), else the one not on screen this frame, opening the second on demand.
    pub fn get(
        &mut self,
        d3d: &D3d,
        path: &str,
        stream: u32,
        full_range: bool,
        src_t: f64,
    ) -> Result<&mut VideoStream> {
        let key = (path.to_string(), stream);
        let frame_no = self.frame_no;
        let entry = self.slots.entry(key).or_default();
        if entry.is_empty() {
            entry.push(Slot {
                vs: VideoStream::open(d3d, path, stream, full_range)
                    .map_err(|e| e.context(format!("open {path}#{stream}")))?,
                used_frame: 0,
                touch: frame_no,
                touched_at: std::time::Instant::now(),
            });
        }
        let fitness = |s: &Slot| -> i32 {
            let near_last = s.vs.last_pts >= 0.0
                && src_t >= s.vs.last_pts - 0.05
                // at EOS the shown frame IS correct for any later src_t (freeze-frame) —
                // without this, get() opened doomed spares for past-the-end requests
                && (src_t < s.vs.last_pts + 1.0 || s.vs.eos);
            let primed = s
                .vs
                .pending_pts()
                .map(|p| (p - src_t).abs() < 0.5)
                .unwrap_or(false);
            if near_last {
                2
            } else if primed {
                1
            } else {
                0
            }
        };
        let mut best = 0usize;
        for i in 1..entry.len() {
            if fitness(&entry[i]) > fitness(&entry[best]) {
                best = i;
            }
        }
        // nothing fits and the best is on screen this frame -> open/use the spare so the
        // on-screen picture never gets torn away mid-frame
        if fitness(&entry[best]) == 0 && entry[best].used_frame == frame_no {
            if entry.len() < 3 {
                entry.push(Slot {
                    vs: VideoStream::open(d3d, path, stream, full_range)
                        .map_err(|e| e.context(format!("open spare {path}#{stream}")))?,
                    used_frame: 0,
                    touch: frame_no,
                    touched_at: std::time::Instant::now(),
                });
            }
            best = entry.len() - 1;
        }
        entry[best].used_frame = frame_no;
        entry[best].touch = frame_no;
        entry[best].touched_at = std::time::Instant::now();
        Ok(&mut entry[best].vs)
    }

    /// Drop every (path,stream) whose slots have ALL been idle for `keep` composed frames.
    /// Decoder instances accumulate over a long timeline (every pop-out segment is its own
    /// file = its own HW decoder session + 4K textures) — unbounded, that exhausts GPU
    /// memory (0x8007000E) and video production dies permanently.
    pub fn evict_stale(&mut self, keep: u64) {
        let now = self.frame_no;
        self.slots.retain(|_, v| v.iter().any(|s| s.touch + keep > now));
    }

    /// Olive-style idle eviction (aggressive during playback): drop (path,stream) entries
    /// whose slots have ALL been untouched for `max_idle` — bounds GPU memory when playback
    /// sweeps across many files. NOT for paused state (a warm pool is the point there; our
    /// MF opens cost 100-300ms vs Olive's cheap FFmpeg opens).
    pub fn evict_idle(&mut self, max_idle: std::time::Duration) {
        let now = std::time::Instant::now();
        self.slots
            .retain(|_, v| v.iter().any(|s| now.duration_since(s.touched_at) < max_idle));
    }

    /// (open files, open decoder instances) — pool growth watchdog
    pub fn stats(&self) -> (usize, usize) {
        (self.slots.len(), self.slots.values().map(|v| v.len()).sum())
    }

    /// True if (path,stream) already has `n` open instances.
    pub fn has_instances(&self, path: &str, stream: u32, n: usize) -> bool {
        self.slots
            .get(&(path.to_string(), stream))
            .map(|v| v.len() >= n)
            .unwrap_or(false)
    }

    /// Open an instance WITHOUT seeking (idle warm-up: a mid-playback MFCreateSourceReader
    /// on a 14GB original costs ~100-200ms on this thread — never pay it while playing).
    pub fn warm_open(&mut self, d3d: &D3d, path: &str, stream: u32, full_range: bool, instances: usize) -> Result<()> {
        let key = (path.to_string(), stream);
        let frame_no = self.frame_no;
        let entry = self.slots.entry(key).or_default();
        while entry.len() < instances.min(3) {
            entry.push(Slot {
                vs: VideoStream::open(d3d, path, stream, full_range)
                    .map_err(|e| e.context(format!("warm open {path}#{stream}")))?,
                used_frame: 0,
                touch: frame_no,
                touched_at: std::time::Instant::now(),
            });
        }
        Ok(())
    }

    /// Prime the OFF-SCREEN instance at an upcoming in-point (opens the spare if needed).
    pub fn prime_spare(
        &mut self,
        d3d: &D3d,
        path: &str,
        stream: u32,
        full_range: bool,
        src_in: f64,
    ) -> Result<bool> {
        let _ = (d3d, full_range);
        let key = (path.to_string(), stream);
        let frame_no = self.frame_no;
        let Some(entry) = self.slots.get_mut(&key) else {
            return Ok(false); // never OPEN here — warm_open_pass owns opens (idle only)
        };
        if entry.is_empty() {
            return Ok(false);
        }
        // already primed anywhere? done.
        if entry.iter().any(|s| {
            s.vs.pending_pts().map(|p| (p - src_in).abs() < 0.4).unwrap_or(false)
                || (s.vs.last_pts - src_in).abs() < 0.4
        }) {
            return Ok(false);
        }
        let Some(spare) = entry.iter().position(|s| s.used_frame != frame_no) else {
            return Ok(false);
        };
        entry[spare].touch = frame_no; // primed-for-soon: not eviction fodder
        entry[spare].touched_at = std::time::Instant::now();
        entry[spare].vs.prime_step(src_in)?;
        Ok(true)
    }
}

// ---------------- audio ----------------
pub struct AudioDecoder {
    reader: IMFSourceReader,
    pub fifo: VecDeque<f32>,
    pub eos: bool,
}

impl AudioDecoder {
    pub fn open(path: &str, rate: u32, ch: usize) -> Result<Self> {
        unsafe {
            let wp = wide(path);
            let reader = MFCreateSourceReaderFromURL(PCWSTR(wp.as_ptr()), None)?;
            let ty = MFCreateMediaType()?;
            ty.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Audio)?;
            ty.SetGUID(&MF_MT_SUBTYPE, &MFAudioFormat_Float)?;
            ty.SetUINT32(&MF_MT_AUDIO_SAMPLES_PER_SECOND, rate)?;
            ty.SetUINT32(&MF_MT_AUDIO_NUM_CHANNELS, ch as u32)?;
            ty.SetUINT32(&MF_MT_AUDIO_BITS_PER_SAMPLE, 32)?;
            reader.SetCurrentMediaType(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32, None, &ty)?;
            let _ = reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false);
            reader.SetStreamSelection(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32, true)?;
            Ok(Self { reader, fifo: VecDeque::new(), eos: false })
        }
    }
    pub fn pump(&mut self, rate: u32, ch: usize) -> Result<Option<(f64, f64)>> {
        if self.eos {
            return Ok(None);
        }
        unsafe {
            let mut flags = 0u32;
            let mut sample: Option<IMFSample> = None;
            let mut pts = 0i64;
            self.reader.ReadSample(
                MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32,
                0,
                None,
                Some(&mut flags),
                Some(&mut pts),
                Some(&mut sample),
            )?;
            if flags & MF_SOURCE_READERF_ENDOFSTREAM.0 as u32 != 0 {
                self.eos = true;
                return Ok(None);
            }
            let Some(sample) = sample else { return Ok(Some((pts as f64 / HNS, 0.0))) };
            let buf = sample.ConvertToContiguousBuffer()?;
            let mut data: *mut u8 = core::ptr::null_mut();
            let mut len = 0u32;
            buf.Lock(&mut data, None, Some(&mut len))?;
            let floats = std::slice::from_raw_parts(data as *const f32, len as usize / 4);
            self.fifo.extend(floats.iter().copied());
            buf.Unlock()?;
            Ok(Some((pts as f64 / HNS, floats.len() as f64 / ch as f64 / rate as f64)))
        }
    }
    fn seek(&mut self, t: f64, rate: u32, ch: usize) -> Result<()> {
        unsafe {
            let pv = PROPVARIANT::from((t * HNS) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        self.fifo.clear();
        self.eos = false;
        loop {
            let Some((pts, dur)) = self.pump(rate, ch)? else { break };
            if pts + dur >= t {
                let skip = ((t - pts).max(0.0) * rate as f64) as usize * ch;
                let n = skip.min(self.fifo.len());
                self.fifo.drain(..n);
                break;
            }
            self.fifo.clear();
        }
        Ok(())
    }
    fn pull(&mut self, out: &mut [f32], rate: u32, ch: usize) -> Result<()> {
        while self.fifo.len() < out.len() && !self.eos {
            self.pump(rate, ch)?;
        }
        for v in out.iter_mut() {
            *v = self.fifo.pop_front().unwrap_or(0.0);
        }
        Ok(())
    }
}

/// WASAPI shared render + per-asset decoders. `clock()` (frames played) is the master
/// clock while playing. `fill()` pulls PCM according to the document's audio track.
pub struct AudioOut {
    pub underruns: u64,
    latency_s: f64,
    client: IAudioClient,
    render: IAudioRenderClient,
    pub rate: u32,
    pub ch: usize,
    buffer_frames: u32,
    frames_written: u64,
    base_t: f64, // timeline time at frames_written==0 (set on play/seek)
    speed: f64,
    streams: HashMap<String, ClipStream>, // keyed by CLIP id — overlapping clips mix
    scratch: Vec<f32>,
    fills: u64,
    last_mixed: usize,
    started: bool,
}

/// One decoded audio lane clip. next_src_t tracks continuity so sequential fills
/// don't re-seek; a jump (scrub/loop) re-seeks just this stream.
struct ClipStream {
    dec: AudioDecoder,
    next_src_t: f64,
    last_used: u64,
    stretch: Option<timestretch::StreamProcessor>,
    stretch_speed: f64,
    stretch_fifo: VecDeque<f32>,
    stretch_last: Vec<f32>,
}

impl AudioOut {
    pub fn new() -> Result<Self> {
        unsafe {
            let en: IMMDeviceEnumerator = CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
            let dev = en.GetDefaultAudioEndpoint(eRender, eConsole)?;
            let client: IAudioClient = dev.Activate(CLSCTX_ALL, None)?;
            let fmt = client.GetMixFormat()?;
            let rate = (*fmt).nSamplesPerSec;
            let ch = (*fmt).nChannels as usize;
            client.Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 2_000_000, 0, fmt, None)?;
            let render: IAudioRenderClient = client.GetService()?;
            let buffer_frames = client.GetBufferSize()?;
            // device output latency: the clock must report what is AUDIBLE now, not what was
            // submitted — uncorrected this made video lead the heard audio by ~20-40ms
            // (visible on lip-synced closeups like the pop-out clips)
            let latency_s = client.GetStreamLatency().map(|l| l as f64 / 10_000_000.0).unwrap_or(0.0);
            eprintln!("audio device latency: {:.1}ms", latency_s * 1000.0);
            Ok(Self {
                underruns: 0,
                latency_s,
                client,
                render,
                rate,
                ch,
                buffer_frames,
                frames_written: 0,
                base_t: 0.0,
                speed: 1.0,
                streams: HashMap::new(),
                scratch: Vec::new(),
                fills: 0,
                last_mixed: 0,
                started: false,
            })
        }
    }

    pub fn start_at(&mut self, t: f64, speed: f64) -> Result<()> {
        unsafe {
            if self.started {
                let _ = self.client.Stop();
                let _ = self.client.Reset();
                self.started = false;
            }
        }
        self.frames_written = 0;
        self.base_t = t;
        self.speed = speed.max(0.1);
        for st in self.streams.values_mut() {
            st.next_src_t = f64::NAN; // force a re-seek on the next fill
            if let Some(proc_) = st.stretch.as_mut() {
                proc_.reset();
            }
            st.stretch_fifo.clear();
            st.stretch_last.clear();
        }
        Ok(())
    }

    pub fn stop(&mut self) {
        unsafe {
            if self.started {
                let _ = self.client.Stop();
                let _ = self.client.Reset();
            }
        }
        self.started = false;
    }

    pub fn clock(&self) -> f64 {
        let padding = unsafe { self.client.GetCurrentPadding().unwrap_or(0) } as u64;
        (self.base_t + self.frames_written.saturating_sub(padding) as f64 / self.rate as f64 * self.speed
            - self.latency_s)
            .max(self.base_t)
    }

    pub fn fill(&mut self, doc: &crate::model::Doc, speed: f64) -> Result<()> {
        unsafe {
            let speed = speed.max(0.1);
            if (speed - self.speed).abs() > 0.01 {
                let cur = self.clock();
                self.start_at(cur, speed)?;
            }
            let padding = self.client.GetCurrentPadding()?;
            if self.started && padding == 0 {
                self.underruns += 1; // the device ran dry — this is an audible break
            }
            let avail = self.buffer_frames - padding;
            if avail == 0 {
                if !self.started {
                    self.client.Start()?;
                    self.started = true;
                }
                return Ok(());
            }
            let ptr = self.render.GetBuffer(avail)?;
            let out = std::slice::from_raw_parts_mut(ptr as *mut f32, avail as usize * self.ch);
            let (rate, ch) = (self.rate, self.ch);
            for v in out.iter_mut() {
                *v = 0.0;
            }
            // MIX every audible audio-lane clip overlapping this buffer window — stacked
            // clips all play (an NLE mixes; it does not pick one), volume 0 = silent
            let t0 = self.base_t + self.frames_written as f64 / rate as f64 * speed;
            let t1 = t0 + avail as f64 / rate as f64 * speed;
            self.fills += 1;
            let fills = self.fills;
            let mut scratch = std::mem::take(&mut self.scratch);
            let mut mixed = 0usize;
            let any_solo = doc.seq.tracks.iter().any(|t| t.solo);
            for (own, c) in doc.active_audio_span(t0, t1) {
                // lane header flags: linked audio follows its VISUAL clip's lane
                let gov = doc.audio_gov_track(c, own);
                if let Some(gtr) = doc.seq.tracks.get(gov) {
                    if gtr.muted || (any_solo && !gtr.solo) {
                        continue;
                    }
                }
                let Some(aid) = c.asset_id.as_deref() else { continue };
                let vol = c.volume as f32;
                if vol <= 0.001 {
                    continue;
                }
                let s0 = (((c.timeline_start - t0).max(0.0) / speed) * rate as f64).round() as usize;
                let s1 = ((((c.timeline_end.min(t1)) - t0) / speed * rate as f64).round() as usize)
                    .min(avail as usize);
                if s1 <= s0 {
                    continue;
                }
                if !self.streams.contains_key(&c.id) {
                    let path = doc.asset_path(aid);
                    match AudioDecoder::open(&path, rate, ch) {
                        Ok(dec) => {
                            self.streams.insert(
                                c.id.clone(),
                                ClipStream {
                                    dec,
                                    next_src_t: f64::NAN,
                                    last_used: fills,
                                    stretch: None,
                                    stretch_speed: 1.0,
                                    stretch_fifo: VecDeque::new(),
                                    stretch_last: Vec::new(),
                                },
                            );
                        }
                        Err(_) => continue, // asset without a decodable audio stream
                    }
                }
                let st = self.streams.get_mut(&c.id).unwrap();
                st.last_used = fills;
                let src_t = c.source_start + (t0 + s0 as f64 / rate as f64 * speed) - c.timeline_start;
                let buffered_stretch = speed > 1.01 && !st.stretch_fifo.is_empty();
                let discontinuity = !st.next_src_t.is_finite()
                    || (!buffered_stretch && (st.next_src_t - src_t).abs() > 0.08);
                if discontinuity {
                    if st.dec.seek(src_t, rate, ch).is_err() {
                        continue;
                    }
                    st.next_src_t = src_t;
                    if let Some(proc_) = st.stretch.as_mut() {
                        proc_.reset();
                    }
                    st.stretch_fifo.clear();
                    st.stretch_last.clear();
                }
                let out_frames = s1 - s0;
                if speed <= 1.01 {
                    let n = out_frames * ch;
                    scratch.clear();
                    scratch.resize(n, 0.0);
                    if st.dec.pull(&mut scratch[..n], rate, ch).is_err() {
                        continue;
                    }
                    st.next_src_t = src_t + out_frames as f64 / rate as f64;
                    for (o, sv) in out[s0 * ch..s1 * ch].iter_mut().zip(scratch.iter()) {
                        *o += *sv * vol;
                    }
                } else {
                    if st.stretch.is_none() || (st.stretch_speed - speed).abs() > 0.01 {
                        let params = timestretch::StretchParams::new(1.0 / speed)
                            .with_sample_rate(rate)
                            .with_channels(ch as u32)
                            .with_preset(timestretch::EdmPreset::VocalChop)
                            .with_quality_mode(timestretch::QualityMode::Balanced);
                        st.stretch = Some(timestretch::StreamProcessor::new(params));
                        st.stretch_speed = speed;
                        st.stretch_fifo.clear();
                        st.stretch_last.clear();
                    }
                    let need = out_frames * ch;
                    let target_fifo = need + ((rate as usize / 4).max(2048) * ch);
                    let mut guard = 0usize;
                    while st.stretch_fifo.len() < target_fifo && guard < 4 {
                        guard += 1;
                        let missing_frames = ((target_fifo - st.stretch_fifo.len()) / ch).max(out_frames);
                        let src_frames = ((missing_frames as f64 * speed).ceil() as usize + rate as usize / 8)
                            .clamp(4096, rate as usize);
                        let n = src_frames * ch;
                        scratch.clear();
                        scratch.resize(n, 0.0);
                        if st.dec.pull(&mut scratch[..n], rate, ch).is_err() {
                            break;
                        }
                        st.next_src_t += src_frames as f64 / rate as f64;
                        let mut stretched = Vec::with_capacity(need + 65_536);
                        if let Some(proc_) = st.stretch.as_mut() {
                            let _ = proc_.process_into(&scratch, &mut stretched);
                        }
                        st.stretch_fifo.extend(stretched);
                    }
                    if st.stretch_last.len() != ch {
                        st.stretch_last.resize(ch, 0.0);
                    }
                    for (idx, o) in out[s0 * ch..s1 * ch].iter_mut().enumerate() {
                        let cc = idx % ch;
                        let sv = if let Some(v) = st.stretch_fifo.pop_front() {
                            st.stretch_last[cc] = v;
                            v
                        } else {
                            st.stretch_last[cc]
                        };
                        *o += sv * vol;
                    }
                }
                mixed += 1;
            }
            self.scratch = scratch;
            if mixed != self.last_mixed {
                eprintln!("AMIX {mixed} clips");
                self.last_mixed = mixed;
            }
            for v in out.iter_mut() {
                *v = v.clamp(-1.0, 1.0);
            }
            // drop decoders idle for ~4s of fills (each fill ≈ 10ms device period)
            self.streams.retain(|_, st| fills - st.last_used < 400);
            self.render.ReleaseBuffer(avail, 0)?;
            self.frames_written += avail as u64;
            if !self.started {
                self.client.Start()?;
                self.started = true;
            }
            Ok(())
        }
    }
}
