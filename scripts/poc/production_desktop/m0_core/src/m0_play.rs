//! M0 gate #2 — real windowed playback with an AUDIO-MASTER clock across clip boundaries.
//!
//! The architecture decision under test: video is SLAVED to the WASAPI audio clock
//! (frames are presented when the audio clock reaches their timestamp), and every clip's
//! decoder is pre-opened + pre-seeked (decoder pool) so a boundary is just "switch which
//! prefetched frame we present" — no pipeline, no flush, no gap, A/V desync structurally
//! impossible.
//!
//! Plays a hardcoded 3-clip timeline (2 assets → 2 hard boundaries) and reports:
//!   - inter-present gap: max/p95 near boundaries vs elsewhere (goal: no boundary spike)
//!   - A/V offset stats (presented video pts vs audio clock; goal: |offset| < 1 frame)
//! Window class M0Play — screenshot-able while running.

use std::collections::VecDeque;
use std::time::Instant;

use anyhow::{bail, Result};
use windows::core::{w, Interface, GUID, PCWSTR, PROPVARIANT};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::*;
use windows::Win32::Graphics::Dxgi::*;
use windows::Win32::Media::Audio::*;
use windows::Win32::Media::MediaFoundation::*;
use windows::Win32::System::Com::*;
use windows::Win32::UI::WindowsAndMessaging::*;

const HNS: i64 = 10_000_000;

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

// ---------------- timeline (hardcoded for the gate) ----------------
struct Clip {
    asset: usize, // index into assets
    src_in: f64,
    dur: f64,
}

// ---------------- video: pull-based frame server with 1-frame lookahead ----------------
struct VideoServer {
    reader: IMFSourceReader,
    width: u32,
    height: u32,
    rotation: u32,
    pending: Option<(f64, IMFSample)>, // decoded-ahead frame (source pts)
}

impl VideoServer {
    fn open(device: &ID3D11Device, mgr: &IMFDXGIDeviceManager, path: &str) -> Result<Self> {
        unsafe {
            let _ = device;
            let mut attrs: Option<IMFAttributes> = None;
            MFCreateAttributes(&mut attrs, 4)?;
            let attrs = attrs.unwrap();
            attrs.SetUnknown(&MF_SOURCE_READER_D3D_MANAGER, mgr)?;
            attrs.SetUINT32(&MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1)?;
            attrs.SetUINT32(&MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, 1)?;
            let wp = wide(path);
            let reader = MFCreateSourceReaderFromURL(PCWSTR(wp.as_ptr()), &attrs)?;
            let ty = MFCreateMediaType()?;
            ty.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            ty.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_NV12)?;
            reader.SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32, None, &ty)?;
            let _ = reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false);
            reader.SetStreamSelection(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32, true)?;
            let cur = reader.GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32)?;
            let sz = cur.GetUINT64(&MF_MT_FRAME_SIZE)?;
            let rotation = cur.GetUINT32(&MF_MT_VIDEO_ROTATION).unwrap_or(0);
            Ok(Self {
                reader,
                width: (sz >> 32) as u32,
                height: (sz & 0xffff_ffff) as u32,
                rotation,
                pending: None,
            })
        }
    }

    fn read_next(&mut self) -> Result<Option<(f64, IMFSample)>> {
        unsafe {
            let mut flags = 0u32;
            let mut sample: Option<IMFSample> = None;
            let mut pts = 0i64;
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
            Ok(sample.map(|s| (pts as f64 / HNS as f64, s)))
        }
    }

    /// Pre-seek so the frame AT src_t is buffered in `pending` (a boundary becomes a no-op).
    fn preroll(&mut self, src_t: f64) -> Result<()> {
        unsafe {
            let pv = PROPVARIANT::from((src_t * HNS as f64) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        self.pending = None;
        while let Some((pts, s)) = self.read_next()? {
            if pts + 0.0005 >= src_t {
                self.pending = Some((pts, s));
                break;
            }
        }
        Ok(())
    }

    /// Newest frame with pts <= src_t (advance through pending); None = keep last presented.
    fn frame_for(&mut self, src_t: f64) -> Result<Option<(f64, IMFSample)>> {
        let mut out = None;
        loop {
            match &self.pending {
                Some((pts, _)) if *pts <= src_t => {
                    out = self.pending.take();
                    self.pending = self.read_next()?;
                }
                _ => break,
            }
        }
        Ok(out)
    }
}

// ---------------- audio: per-asset PCM pull (mix-format) ----------------
struct AudioServer {
    reader: IMFSourceReader,
    fifo: VecDeque<f32>, // interleaved, mix format
    channels: usize,
    rate: u32,
    eos: bool,
}

impl AudioServer {
    fn open(path: &str, rate: u32, channels: usize) -> Result<Self> {
        unsafe {
            let wp = wide(path);
            let reader = MFCreateSourceReaderFromURL(PCWSTR(wp.as_ptr()), None)?;
            let ty = MFCreateMediaType()?;
            ty.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Audio)?;
            ty.SetGUID(&MF_MT_SUBTYPE, &MFAudioFormat_Float)?;
            ty.SetUINT32(&MF_MT_AUDIO_SAMPLES_PER_SECOND, rate)?;
            ty.SetUINT32(&MF_MT_AUDIO_NUM_CHANNELS, channels as u32)?;
            ty.SetUINT32(&MF_MT_AUDIO_BITS_PER_SAMPLE, 32)?;
            reader.SetCurrentMediaType(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32, None, &ty)?;
            let _ = reader.SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS.0 as u32, false);
            reader.SetStreamSelection(MF_SOURCE_READER_FIRST_AUDIO_STREAM.0 as u32, true)?;
            Ok(Self { reader, fifo: VecDeque::new(), channels, rate, eos: false })
        }
    }

    fn seek(&mut self, src_t: f64) -> Result<()> {
        unsafe {
            let pv = PROPVARIANT::from((src_t * HNS as f64) as i64);
            self.reader.SetCurrentPosition(&GUID::zeroed(), &pv)?;
        }
        self.fifo.clear();
        self.eos = false;
        // decode forward and drop samples before src_t so audio starts EXACTLY at the in-point
        loop {
            let Some((pts, dur)) = self.pump()? else { break };
            if pts + dur >= src_t {
                let skip = ((src_t - pts).max(0.0) * self.rate as f64) as usize * self.channels;
                for _ in 0..skip.min(self.fifo.len()) {
                    self.fifo.pop_front();
                }
                break;
            }
            self.fifo.clear();
        }
        Ok(())
    }

    /// Decode one audio sample into the fifo; returns (pts, duration).
    fn pump(&mut self) -> Result<Option<(f64, f64)>> {
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
            let Some(sample) = sample else { return Ok(Some((pts as f64 / HNS as f64, 0.0))) };
            let buf = sample.ConvertToContiguousBuffer()?;
            let mut data: *mut u8 = core::ptr::null_mut();
            let mut len = 0u32;
            buf.Lock(&mut data, None, Some(&mut len))?;
            let floats = std::slice::from_raw_parts(data as *const f32, len as usize / 4);
            self.fifo.extend(floats.iter().copied());
            buf.Unlock()?;
            let dur = floats.len() as f64 / self.channels as f64 / self.rate as f64;
            Ok(Some((pts as f64 / HNS as f64, dur)))
        }
    }

    fn pull(&mut self, out: &mut [f32]) -> Result<()> {
        while self.fifo.len() < out.len() && !self.eos {
            self.pump()?;
        }
        for v in out.iter_mut() {
            *v = self.fifo.pop_front().unwrap_or(0.0);
        }
        Ok(())
    }
}

// ---------------- window ----------------
unsafe extern "system" fn wndproc(h: HWND, m: u32, w: WPARAM, l: LPARAM) -> LRESULT {
    match m {
        WM_DESTROY => {
            PostQuitMessage(0);
            LRESULT(0)
        }
        _ => DefWindowProcW(h, m, w, l),
    }
}

fn stats_ms(mut v: Vec<f64>) -> (f64, f64, f64) {
    if v.is_empty() {
        return (0.0, 0.0, 0.0);
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    (v[n / 2], v[((n as f64 * 0.95) as usize).min(n - 1)], v[n - 1])
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        bail!("usage: m0_play <videoA> <videoB>");
    }

    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        MFStartup(MF_VERSION, MFSTARTUP_FULL)?;
    }

    // ---- D3D11 + DXGI manager ----
    let (device, mgr) = unsafe {
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
        (device, mgr)
    };
    let ctx = unsafe { device.GetImmediateContext()? };

    // ---- window + swapchain (480x854 portrait-ish preview) ----
    let (win_w, win_h) = (480i32, 854i32);
    let hwnd = unsafe {
        let hinst = windows::Win32::System::LibraryLoader::GetModuleHandleW(None)?;
        let cls = w!("M0Play");
        let wc = WNDCLASSW {
            lpfnWndProc: Some(wndproc),
            hInstance: hinst.into(),
            lpszClassName: cls,
            ..Default::default()
        };
        RegisterClassW(&wc);
        CreateWindowExW(
            WINDOW_EX_STYLE(0),
            cls,
            w!("M0 playback core"),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            60,
            60,
            win_w,
            win_h,
            None,
            None,
            hinst,
            None,
        )?
    };
    let swap: IDXGISwapChain1 = unsafe {
        let dxgi_dev: IDXGIDevice = device.cast()?;
        let adapter = dxgi_dev.GetAdapter()?;
        let factory: IDXGIFactory2 = adapter.GetParent()?;
        let desc = DXGI_SWAP_CHAIN_DESC1 {
            Width: win_w as u32,
            Height: win_h as u32,
            Format: DXGI_FORMAT_B8G8R8A8_UNORM,
            SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
            BufferUsage: DXGI_USAGE_RENDER_TARGET_OUTPUT,
            BufferCount: 2,
            SwapEffect: DXGI_SWAP_EFFECT_FLIP_DISCARD,
            ..Default::default()
        };
        factory.CreateSwapChainForHwnd(&device, hwnd, &desc, None, None)?
    };
    let backbuf: ID3D11Texture2D = unsafe { swap.GetBuffer(0)? };

    // ---- assets + timeline: A ... | B ... | A ... (2 hard boundaries) ----
    let asset_paths = [args[1].clone(), args[2].clone()];
    let mut vservers: Vec<VideoServer> = asset_paths
        .iter()
        .map(|p| VideoServer::open(&device, &mgr, p))
        .collect::<Result<_>>()?;
    let timeline = [
        Clip { asset: 0, src_in: 203.5, dur: 3.0 },
        Clip { asset: 1, src_in: 10.0, dur: 3.0 },
        Clip { asset: 0, src_in: 300.0, dur: 3.0 },
    ];
    let boundaries = [3.0f64, 6.0];
    let total: f64 = timeline.iter().map(|c| c.dur).sum();

    // ---- video processor (NV12 -> RGB, rotation, letterbox) ----
    let vdev: ID3D11VideoDevice = device.cast()?;
    let vctx: ID3D11VideoContext = ctx.cast()?;
    let (vw, vh) = (vservers[0].width, vservers[0].height);
    let vp_enum = unsafe {
        vdev.CreateVideoProcessorEnumerator(&D3D11_VIDEO_PROCESSOR_CONTENT_DESC {
            InputFrameFormat: D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE,
            InputFrameRate: DXGI_RATIONAL { Numerator: 30, Denominator: 1 },
            InputWidth: vw,
            InputHeight: vh,
            OutputFrameRate: DXGI_RATIONAL { Numerator: 60, Denominator: 1 },
            OutputWidth: win_w as u32,
            OutputHeight: win_h as u32,
            Usage: D3D11_VIDEO_USAGE_PLAYBACK_NORMAL,
        })?
    };
    let vp = unsafe { vdev.CreateVideoProcessor(&vp_enum, 0)? };
    let out_view = unsafe {
        let mut ov: Option<ID3D11VideoProcessorOutputView> = None;
        vdev.CreateVideoProcessorOutputView(
            &backbuf,
            &vp_enum,
            &D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC {
                ViewDimension: D3D11_VPOV_DIMENSION_TEXTURE2D,
                Anonymous: D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC_0 {
                    Texture2D: D3D11_TEX2D_VPOV { MipSlice: 0 },
                },
            },
            Some(&mut ov),
        )?;
        ov.unwrap()
    };

    // ---- WASAPI (shared, audio-master clock) ----
    let (audio_client, render, mix_rate, mix_ch) = unsafe {
        let en: IMMDeviceEnumerator = CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
        let dev = en.GetDefaultAudioEndpoint(eRender, eConsole)?;
        let client: IAudioClient = dev.Activate(CLSCTX_ALL, None)?;
        let fmt = client.GetMixFormat()?;
        let rate = (*fmt).nSamplesPerSec;
        let ch = (*fmt).nChannels as usize;
        client.Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 2_000_000, 0, fmt, None)?; // 200ms buffer
        let render: IAudioRenderClient = client.GetService()?;
        (client, render, rate, ch)
    };
    let buffer_frames = unsafe { audio_client.GetBufferSize()? };

    let mut aservers: Vec<AudioServer> = asset_paths
        .iter()
        .map(|p| AudioServer::open(p, mix_rate, mix_ch))
        .collect::<Result<_>>()?;

    // preroll EVERYTHING before starting (decoder pool: boundaries pre-seeked)
    for (i, c) in timeline.iter().enumerate() {
        if i == 0 || timeline[i - 1].asset != c.asset {
            vservers[c.asset].preroll(c.src_in)?;
        }
    }
    aservers[timeline[0].asset].seek(timeline[0].src_in)?;

    // map timeline time -> (clip idx, source time)
    let locate = |t: f64| -> (usize, f64) {
        let mut acc = 0.0;
        for (i, c) in timeline.iter().enumerate() {
            if t < acc + c.dur || i == timeline.len() - 1 {
                return (i, c.src_in + (t - acc));
            }
            acc += c.dur;
        }
        (0, timeline[0].src_in)
    };

    // ---- play: audio thread fills WASAPI; main thread presents video by audio clock ----
    let mut frames_written: u64 = 0;
    let mut cur_audio_clip = 0usize;
    let mut fill = |aservers: &mut Vec<AudioServer>, cur_audio_clip: &mut usize, frames_written: &mut u64| -> Result<()> {
        unsafe {
            let padding = audio_client.GetCurrentPadding()?;
            let avail = buffer_frames - padding;
            if avail == 0 {
                return Ok(());
            }
            let ptr = render.GetBuffer(avail)?;
            let out = std::slice::from_raw_parts_mut(ptr as *mut f32, avail as usize * mix_ch);
            // pull per timeline position of the WRITE head (frames_written)
            let mut done = 0usize;
            while done < avail as usize {
                let t_write = *frames_written as f64 / mix_rate as f64 + done as f64 / mix_rate as f64;
                let (ci, src_t) = locate(t_write);
                let c = &timeline[ci];
                if ci != *cur_audio_clip {
                    aservers[c.asset].seek(src_t)?;
                    *cur_audio_clip = ci;
                }
                // frames until clip end
                let acc: f64 = timeline[..ci].iter().map(|c| c.dur).sum();
                let left = ((acc + c.dur - t_write) * mix_rate as f64).ceil() as usize;
                let n = left.min(avail as usize - done).max(1);
                aservers[c.asset].pull(&mut out[done * mix_ch..(done + n) * mix_ch])?;
                done += n;
            }
            render.ReleaseBuffer(avail, 0)?;
            *frames_written += avail as u64;
            Ok(())
        }
    };

    fill(&mut aservers, &mut cur_audio_clip, &mut frames_written)?;
    unsafe { audio_client.Start()? };
    let t_start = Instant::now();

    let mut present_times: Vec<(f64, Instant)> = Vec::new(); // (timeline t, wall)
    let mut av_offsets: Vec<f64> = Vec::new();
    let mut cur_vclip = usize::MAX;
    let mut msg = MSG::default();

    loop {
        unsafe {
            while PeekMessageW(&mut msg, None, 0, 0, PM_REMOVE).as_bool() {
                let _ = TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        }
        fill(&mut aservers, &mut cur_audio_clip, &mut frames_written)?;

        // audio-master clock = frames actually played
        let padding = unsafe { audio_client.GetCurrentPadding()? } as u64;
        let t_audio = (frames_written.saturating_sub(padding as u64)) as f64 / mix_rate as f64;
        if t_audio >= total - 0.05 {
            break;
        }
        let (ci, src_t) = locate(t_audio);
        cur_vclip = if cur_vclip == usize::MAX { ci } else { cur_vclip };
        if ci != cur_vclip {
            cur_vclip = ci; // decoder was pre-seeked — switching is free
        }
        let c = &timeline[ci];
        if let Some((pts, sample)) = vservers[c.asset].frame_for(src_t)? {
            unsafe {
                let buf = sample.GetBufferByIndex(0)?;
                let dxgi: IMFDXGIBuffer = buf.cast()?;
                let mut texp: *mut core::ffi::c_void = core::ptr::null_mut();
                dxgi.GetResource(&ID3D11Texture2D::IID, &mut texp)?;
                let tex = ID3D11Texture2D::from_raw(texp);
                let sub = dxgi.GetSubresourceIndex().unwrap_or(0);
                let mut iv: Option<ID3D11VideoProcessorInputView> = None;
                vdev.CreateVideoProcessorInputView(
                    &tex,
                    &vp_enum,
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
                vctx.VideoProcessorBlt(&vp, &out_view, 0, std::slice::from_ref(&stream))?;
                std::mem::ManuallyDrop::drop(&mut stream.pInputSurface);
                swap.Present(1, DXGI_PRESENT(0)).ok()?;
            }
            let acc: f64 = timeline[..ci].iter().map(|c| c.dur).sum();
            let t_frame = acc + (pts - c.src_in);
            present_times.push((t_frame, Instant::now()));
            av_offsets.push((t_frame - t_audio) * 1000.0);
        } else {
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    }
    unsafe { audio_client.Stop()? };
    let wall = t_start.elapsed().as_secs_f64();

    // ---- metrics ----
    let mut gaps_boundary: Vec<f64> = Vec::new();
    let mut gaps_normal: Vec<f64> = Vec::new();
    for w in present_times.windows(2) {
        let gap = w[1].1.duration_since(w[0].1).as_secs_f64() * 1000.0;
        let near = boundaries.iter().any(|b| (w[1].0 - b).abs() < 0.5);
        if near {
            gaps_boundary.push(gap);
        } else {
            gaps_normal.push(gap);
        }
    }
    let (nm, np95, nmax) = stats_ms(gaps_normal.clone());
    let (bm, bp95, bmax) = stats_ms(gaps_boundary.clone());
    let (am, ap95, amax) = stats_ms(av_offsets.iter().map(|v| v.abs()).collect());
    println!("played {:.1}s wall for {:.1}s timeline, {} frames presented", wall, total, present_times.len());
    println!("present gap NORMAL  : median={nm:.1}ms p95={np95:.1}ms max={nmax:.1}ms ({} samples)", gaps_normal.len());
    println!("present gap BOUNDARY: median={bm:.1}ms p95={bp95:.1}ms max={bmax:.1}ms ({} samples)", gaps_boundary.len());
    println!("A/V offset |video-audio|: median={am:.1}ms p95={ap95:.1}ms max={amax:.1}ms");
    let ok = bmax < 50.0 && ap95 < 40.0;
    println!("{}", if ok { "M0 PLAY OK (boundary gapless, audio-master sync)" } else { "M0 PLAY NG" });
    unsafe { DestroyWindow(hwnd)? };
    Ok(())
}
