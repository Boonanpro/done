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
    reader: IMFSourceReader,
    stream: u32,
    pub width: u32,
    pub height: u32,
    pending: Option<(f64, IMFSample)>,
    last_pts: f64,
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
            attrs.SetUINT32(&MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, 1)?;
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
            Ok(Self {
                reader,
                stream,
                width,
                height,
                pending: None,
                last_pts: -1.0,
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
                return Ok(None);
            }
            Ok(sample.map(|s| (pts as f64 / HNS, s)))
        }
    }

    fn seek(&mut self, t: f64) -> Result<()> {
        unsafe {
            let pv = PROPVARIANT::from((t * HNS) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        self.pending = None;
        while let Some((pts, s)) = self.read_next()? {
            if pts + 0.0005 >= t {
                self.pending = Some((pts, s));
                break;
            }
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

    /// Ensure `bgra` holds the newest frame with pts <= t. Seeks on backward/far-forward jumps.
    pub fn ensure_frame(&mut self, d3d: &D3d, t: f64) -> Result<bool> {
        let jump = t < self.last_pts - 0.05 || t > self.last_pts + 1.0 || self.last_pts < 0.0;
        if jump {
            self.seek(t)?;
            // present the first frame at/after t immediately (scrub shows something NOW)
            if let Some((pts, s)) = self.pending.take() {
                self.blit(d3d, &s)?;
                self.last_pts = pts;
                self.pending = self.read_next()?;
            }
            return Ok(self.has_frame);
        }
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

/// Pool of open video streams keyed by (path, stream index).
pub struct VideoPool {
    pub streams: HashMap<(String, u32), VideoStream>,
}

impl VideoPool {
    pub fn new() -> Self {
        Self { streams: HashMap::new() }
    }
    pub fn get(&mut self, d3d: &D3d, path: &str, stream: u32, full_range: bool) -> Result<&mut VideoStream> {
        let key = (path.to_string(), stream);
        if !self.streams.contains_key(&key) {
            let vs = VideoStream::open(d3d, path, stream, full_range)?;
            self.streams.insert(key.clone(), vs);
        }
        Ok(self.streams.get_mut(&key).unwrap())
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
    latency_s: f64,
    client: IAudioClient,
    render: IAudioRenderClient,
    pub rate: u32,
    pub ch: usize,
    buffer_frames: u32,
    frames_written: u64,
    base_t: f64, // timeline time at frames_written==0 (set on play/seek)
    decoders: HashMap<String, AudioDecoder>,
    cur_clip: Option<(String, f64, f64)>, // (clip id, timeline_start, source_start)
    started: bool,
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
                latency_s,
                client,
                render,
                rate,
                ch,
                buffer_frames,
                frames_written: 0,
                base_t: 0.0,
                decoders: HashMap::new(),
                cur_clip: None,
                started: false,
            })
        }
    }

    pub fn start_at(&mut self, t: f64) -> Result<()> {
        unsafe {
            if self.started {
                let _ = self.client.Stop();
                let _ = self.client.Reset();
                self.started = false;
            }
        }
        self.frames_written = 0;
        self.base_t = t;
        self.cur_clip = None;
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
        (self.base_t + self.frames_written.saturating_sub(padding) as f64 / self.rate as f64
            - self.latency_s)
            .max(self.base_t)
    }

    pub fn fill(&mut self, doc: &crate::model::Doc) -> Result<()> {
        unsafe {
            let padding = self.client.GetCurrentPadding()?;
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
            let mut done = 0usize;
            while done < avail as usize {
                let t_write = self.base_t + (self.frames_written as f64 + done as f64) / rate as f64;
                match doc.active_audio(t_write) {
                    Some(c) => {
                        let path = doc.asset_path(c.asset_id.as_deref().unwrap());
                        let src_t = c.source_start + (t_write - c.timeline_start);
                        let key = c.id.clone();
                        let need_seek = match &self.cur_clip {
                            Some((id, _, _)) => *id != key,
                            None => true,
                        };
                        if !self.decoders.contains_key(&path) {
                            self.decoders.insert(path.clone(), AudioDecoder::open(&path, rate, ch)?);
                        }
                        if need_seek {
                            self.decoders.get_mut(&path).unwrap().seek(src_t, rate, ch)?;
                            self.cur_clip = Some((key, c.timeline_start, c.source_start));
                        }
                        let left = ((c.timeline_end - t_write) * rate as f64).ceil().max(1.0) as usize;
                        let n = left.min(avail as usize - done);
                        self.decoders
                            .get_mut(&path)
                            .unwrap()
                            .pull(&mut out[done * ch..(done + n) * ch], rate, ch)?;
                        done += n;
                    }
                    None => {
                        // silence for 20ms worth or to end of gap
                        let n = (rate as usize / 50).min(avail as usize - done).max(1);
                        for v in out[done * ch..(done + n) * ch].iter_mut() {
                            *v = 0.0;
                        }
                        self.cur_clip = None;
                        done += n;
                    }
                }
            }
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
