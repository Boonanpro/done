//! GPU-direct preview presentation.
//!
//! The old path was: D3D11 compose -> CPU readback (Map + swizzle) -> egui
//! ColorImage -> GL texture re-upload -> present. Under a dense CTA the readback
//! stalled the media thread and the 8MB/frame CPU churn stalled the UI thread —
//! playback froze, frames went stale, captions/images vanished.
//!
//! This module keeps composed frames on the GPU end to end:
//!   media thread: CopyResource(canvas -> pooled texture) + Flush  (no Map, no stall)
//!   UI thread:    CopyResource(pooled -> ONE fixed present texture), then
//!                 WGL_NV_DX_interop2 lock -> draw into eframe's swapchain -> unlock
//! Everything runs on the ONE D3D11 device the whole engine shares (its immediate
//! context is multithread-protected, see media::D3d::new), so the handoff is two
//! GPU-side copies and zero CPU pixel work.
//!
//! The GL side runs WGL_NV_DX_interop2 against a SECOND, UI-thread-only D3D11
//! device. Interop against the engine device itself — which the media thread
//! and MF worker threads pump concurrently — hung the GPU scheduler within
//! seconds (DXGI_ERROR_DEVICE_HUNG, measured), no matter whether textures were
//! registered per-frame or once. The bridge between the two devices is a
//! keyed-mutex shared texture: engine frames are copied in under the mutex on
//! the engine device, taken out under the mutex on the presentation device,
//! and only the presentation device (single-threaded by construction) ever
//! meets the interop lock.
//!
//! Ownership rule for pooled textures: the media thread reuses one for writing
//! only while the pool's Arc is the sole reference (strong_count == 1). The
//! ring, the published frame and the UI's displayed frame all hold Arc clones,
//! so a texture can never be recycled while it is still queued or on screen.

use std::ffi::c_void;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use anyhow::{anyhow, Result};
use eframe::glow::{self, HasContext as _};
use windows::core::Interface;
use windows::Win32::Graphics::Direct3D11::*;
use windows::Win32::Graphics::Dxgi::Common::*;

/// One pooled, GPU-only copy of a composed frame (BGRA, canvas-sized).
pub struct GpuTex {
    pub tex: ID3D11Texture2D,
    pub id: u64,
    /// このフレーム自身の寸法。キャンバス形式の切替直後、UIは「新しい枠」でなく
    /// 「表示中フレームの寸法」で枠を決めることで、旧フレームの引き伸ばし
    /// （一瞬の潰れ）と提示層の空描き（一瞬の黒）を両方なくす。
    pub w: u32,
    pub h: u32,
}

fn create_frame_tex(device: &ID3D11Device, w: u32, h: u32) -> Result<ID3D11Texture2D> {
    let desc = D3D11_TEXTURE2D_DESC {
        Width: w,
        Height: h,
        MipLevels: 1,
        ArraySize: 1,
        Format: DXGI_FORMAT_B8G8R8A8_UNORM,
        SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
        Usage: D3D11_USAGE_DEFAULT,
        BindFlags: D3D11_BIND_SHADER_RESOURCE.0 as u32,
        ..Default::default()
    };
    let mut tex: Option<ID3D11Texture2D> = None;
    unsafe { device.CreateTexture2D(&desc, None, Some(&mut tex))? };
    tex.ok_or_else(|| anyhow!("present texture creation returned none"))
}

/// Bounded recycling pool of presentation textures, shared by the media thread
/// (writer) and the UI thread (reader).
pub struct TexPool {
    pub device: ID3D11Device,
    pub w: u32,
    pub h: u32,
    entries: Mutex<Vec<Arc<GpuTex>>>,
    next_id: AtomicU64,
}

impl TexPool {
    pub fn new(device: ID3D11Device, w: u32, h: u32) -> Self {
        Self { device, w, h, entries: Mutex::new(Vec::new()), next_id: AtomicU64::new(1) }
    }

    /// A texture the media thread may write into: an idle pooled one, else new.
    pub fn acquire(&self) -> Result<Arc<GpuTex>> {
        {
            let entries = self.entries.lock().unwrap();
            if let Some(free) = entries.iter().find(|e| Arc::strong_count(e) == 1) {
                return Ok(free.clone());
            }
        }
        let tex = create_frame_tex(&self.device, self.w, self.h)?;
        let entry =
            Arc::new(GpuTex { tex, id: self.next_id.fetch_add(1, Ordering::Relaxed), w: self.w, h: self.h });
        self.entries.lock().unwrap().push(entry.clone());
        Ok(entry)
    }

    /// Cap the number of IDLE textures (a 3x-speed session grows the ring to ~48
    /// frames; do not keep half a GB of VRAM parked afterwards). In-use entries
    /// are untouched. Pool textures never touch GL, so dropping frees them.
    pub fn trim(&self, keep_free: usize) {
        let mut entries = self.entries.lock().unwrap();
        let mut free_seen = 0usize;
        entries.retain(|e| {
            if Arc::strong_count(e) != 1 {
                return true;
            }
            free_seen += 1;
            free_seen <= keep_free
        });
    }

    pub fn stats(&self) -> (usize, usize) {
        let entries = self.entries.lock().unwrap();
        let free = entries.iter().filter(|e| Arc::strong_count(e) == 1).count();
        (entries.len(), free)
    }
}

// ---------------------------------------------------------------------------
// UI side: WGL_NV_DX_interop2 presenter
// ---------------------------------------------------------------------------

const GL_TEXTURE_2D: u32 = 0x0DE1;
const WGL_ACCESS_READ_ONLY_NV: u32 = 0x0000;

type PfnDxOpenDevice = unsafe extern "system" fn(dx_device: *mut c_void) -> *mut c_void;
type PfnDxRegisterObject = unsafe extern "system" fn(
    h_device: *mut c_void,
    dx_object: *mut c_void,
    name: u32,
    obj_type: u32,
    access: u32,
) -> *mut c_void;
type PfnDxUnregisterObject =
    unsafe extern "system" fn(h_device: *mut c_void, h_object: *mut c_void) -> i32;
type PfnDxLockObjects =
    unsafe extern "system" fn(h_device: *mut c_void, count: i32, objects: *mut *mut c_void) -> i32;

struct WglDx {
    open_device: PfnDxOpenDevice,
    register_object: PfnDxRegisterObject,
    #[allow(dead_code)]
    unregister_object: PfnDxUnregisterObject,
    lock_objects: PfnDxLockObjects,
    unlock_objects: PfnDxLockObjects,
}

fn load_wgl_dx() -> Option<WglDx> {
    unsafe fn load(name: &str) -> Option<unsafe extern "system" fn() -> isize> {
        let c = std::ffi::CString::new(name).ok()?;
        let p = unsafe {
            windows::Win32::Graphics::OpenGL::wglGetProcAddress(windows::core::PCSTR(
                c.as_ptr() as _
            ))
        }?;
        // wglGetProcAddress may return sentinel values instead of NULL
        let v = p as usize;
        if v == 0 || v == 1 || v == 2 || v == 3 || v == usize::MAX {
            return None;
        }
        Some(p)
    }
    unsafe {
        Some(WglDx {
            open_device: std::mem::transmute(load("wglDXOpenDeviceNV")?),
            register_object: std::mem::transmute(load("wglDXRegisterObjectNV")?),
            unregister_object: std::mem::transmute(load("wglDXUnregisterObjectNV")?),
            lock_objects: std::mem::transmute(load("wglDXLockObjectsNV")?),
            unlock_objects: std::mem::transmute(load("wglDXUnlockObjectsNV")?),
        })
    }
}

/// Raw interop handle. Only ever touched on the UI thread with the GL context
/// current; the wrapper exists so the state can live inside Arc<GlVideo>.
#[derive(Clone, Copy)]
struct Hnd(*mut c_void);
unsafe impl Send for Hnd {}
unsafe impl Sync for Hnd {}

struct Ready {
    funcs: WglDx,
    hdev: Hnd,
    program: glow::Program,
    vao: glow::VertexArray,
    /// ENGINE device side: its (multithread-protected) immediate context and the
    /// keyed-mutex shared texture engine frames are copied into.
    ctx1: ID3D11DeviceContext,
    shared1: ID3D11Texture2D,
    km1: windows::Win32::Graphics::Dxgi::IDXGIKeyedMutex,
    /// PRESENTATION device side (UI thread only): its view of the shared
    /// texture, and the ONE fixed local texture GL knows about.
    _dev2: ID3D11Device,
    ctx2: ID3D11DeviceContext,
    shared2: ID3D11Texture2D,
    km2: windows::Win32::Graphics::Dxgi::IDXGIKeyedMutex,
    present: ID3D11Texture2D,
    hobj: Hnd,
    gname: glow::Texture,
    /// id of the pooled frame currently held in `present` — skip the copies when
    /// egui repaints without a new video frame.
    shown_id: u64,
    /// 初期化時のキャンバス寸法。プール寸法と食い違ったら提示層ごと作り直す
    /// （固定寸法の共有テクスチャへの寸法不一致 CopyResource は無言の no-op で、
    /// 形式切替後も最後の旧寸法フレームが新しい枠に引き伸ばされ続けるため）。
    w: u32,
    h: u32,
}

enum GlState {
    Uninit,
    Failed,
    Ready(Box<Ready>),
}

/// The video quad renderer. Lives for the whole app; all methods must be called
/// from inside an egui_glow paint callback (GL context current, viewport already
/// set to the video rect by egui_glow).
pub struct GlVideo {
    state: Mutex<GlState>,
    logged_fail: AtomicBool,
}

unsafe impl Send for GlVideo {}
unsafe impl Sync for GlVideo {}

const VS_SRC: &str = r#"#version 330 core
out vec2 v_uv;
void main() {
    // D3D texel (0,0) is the frame's top-left; map it to the viewport's top-left.
    vec2 c = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.))[gl_VertexID];
    v_uv = c;
    gl_Position = vec4(c.x * 2. - 1., 1. - c.y * 2., 0., 1.);
}"#;

const FS_SRC: &str = r#"#version 330 core
in vec2 v_uv;
out vec4 f;
uniform sampler2D tex;
void main() { f = vec4(texture(tex, v_uv).rgb, 1.0); }
"#;

impl GlVideo {
    pub fn new() -> Self {
        Self { state: Mutex::new(GlState::Uninit), logged_fail: AtomicBool::new(false) }
    }

    fn init(&self, gl: &glow::Context, pool: &TexPool) -> Result<Box<Ready>> {
        use windows::Win32::Graphics::Dxgi::*;
        let funcs = load_wgl_dx()
            .ok_or_else(|| anyhow!("WGL_NV_DX_interop2 not exposed by this GL driver"))?;
        let (ctx1, shared1, km1, dev2, ctx2, shared2, km2, present) = unsafe {
            let ctx1 = pool.device.GetImmediateContext()?;
            // keyed-mutex shared bridge texture on the ENGINE device
            let desc = D3D11_TEXTURE2D_DESC {
                Width: pool.w,
                Height: pool.h,
                MipLevels: 1,
                ArraySize: 1,
                Format: DXGI_FORMAT_B8G8R8A8_UNORM,
                SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
                Usage: D3D11_USAGE_DEFAULT,
                BindFlags: D3D11_BIND_SHADER_RESOURCE.0 as u32,
                MiscFlags: (D3D11_RESOURCE_MISC_SHARED_NTHANDLE.0
                    | D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX.0) as u32,
                ..Default::default()
            };
            let mut tex: Option<ID3D11Texture2D> = None;
            pool.device.CreateTexture2D(&desc, None, Some(&mut tex))?;
            let shared1 = tex.ok_or_else(|| anyhow!("shared texture creation returned none"))?;
            let km1: IDXGIKeyedMutex = shared1.cast()?;
            let handle = shared1.cast::<IDXGIResource1>()?.CreateSharedHandle(
                None,
                (DXGI_SHARED_RESOURCE_READ | DXGI_SHARED_RESOURCE_WRITE).0,
                None,
            )?;
            // presentation device on the SAME adapter, used from this thread only
            let adapter = pool.device.cast::<IDXGIDevice>()?.GetAdapter()?;
            let mut dev2: Option<ID3D11Device> = None;
            windows::Win32::Graphics::Direct3D11::D3D11CreateDevice(
                &adapter,
                windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_UNKNOWN,
                None,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                None,
                D3D11_SDK_VERSION,
                Some(&mut dev2),
                None,
                None,
            )?;
            let dev2 = dev2.ok_or_else(|| anyhow!("presentation device creation failed"))?;
            let ctx2 = dev2.GetImmediateContext()?;
            let shared2: ID3D11Texture2D =
                dev2.cast::<ID3D11Device1>()?.OpenSharedResource1(handle)?;
            let _ = windows::Win32::Foundation::CloseHandle(handle);
            let km2: IDXGIKeyedMutex = shared2.cast()?;
            let present = create_frame_tex(&dev2, pool.w, pool.h)?;
            (ctx1, shared1, km1, dev2, ctx2, shared2, km2, present)
        };
        let hdev = unsafe { (funcs.open_device)(dev2.as_raw()) };
        if hdev.is_null() {
            return Err(anyhow!("wglDXOpenDeviceNV failed ({:?})", unsafe {
                windows::Win32::Foundation::GetLastError()
            }));
        }
        unsafe {
            let program = gl.create_program().map_err(|e| anyhow!("program: {e}"))?;
            let mut shaders = Vec::new();
            for (kind, src) in [(glow::VERTEX_SHADER, VS_SRC), (glow::FRAGMENT_SHADER, FS_SRC)] {
                let sh = gl.create_shader(kind).map_err(|e| anyhow!("shader: {e}"))?;
                gl.shader_source(sh, src);
                gl.compile_shader(sh);
                if !gl.get_shader_compile_status(sh) {
                    return Err(anyhow!("video shader: {}", gl.get_shader_info_log(sh)));
                }
                gl.attach_shader(program, sh);
                shaders.push(sh);
            }
            gl.link_program(program);
            if !gl.get_program_link_status(program) {
                return Err(anyhow!("video program: {}", gl.get_program_info_log(program)));
            }
            for sh in shaders {
                gl.detach_shader(program, sh);
                gl.delete_shader(sh);
            }
            gl.use_program(Some(program));
            let loc = gl.get_uniform_location(program, "tex");
            gl.uniform_1_i32(loc.as_ref(), 0);
            gl.use_program(None);
            let vao = gl.create_vertex_array().map_err(|e| anyhow!("vao: {e}"))?;

            let gname = gl.create_texture().map_err(|e| anyhow!("gl texture: {e}"))?;
            let hobj = (funcs.register_object)(
                hdev,
                present.as_raw(),
                gname.0.get(),
                GL_TEXTURE_2D,
                WGL_ACCESS_READ_ONLY_NV,
            );
            if hobj.is_null() {
                return Err(anyhow!("wglDXRegisterObjectNV failed ({:?})", {
                    windows::Win32::Foundation::GetLastError()
                }));
            }
            // sampling params, set once while GL owns the object
            let mut h = hobj;
            if (funcs.lock_objects)(hdev, 1, &mut h) != 0 {
                gl.bind_texture(glow::TEXTURE_2D, Some(gname));
                gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MIN_FILTER, glow::LINEAR as i32);
                gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MAG_FILTER, glow::LINEAR as i32);
                gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_WRAP_S, glow::CLAMP_TO_EDGE as i32);
                gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_WRAP_T, glow::CLAMP_TO_EDGE as i32);
                gl.bind_texture(glow::TEXTURE_2D, None);
                (funcs.unlock_objects)(hdev, 1, &mut h);
            }
            eprintln!("GPU_PRESENT interop active (GPU-direct preview via presentation device)");
            Ok(Box::new(Ready {
                funcs,
                hdev: Hnd(hdev),
                program,
                vao,
                ctx1,
                shared1,
                km1,
                _dev2: dev2,
                ctx2,
                shared2,
                km2,
                present,
                hobj: Hnd(hobj),
                gname,
                shown_id: 0,
                w: pool.w,
                h: pool.h,
            }))
        }
    }

    /// Draw `frame` into the current viewport. Returns false when interop is
    /// unavailable/broken — the caller then flips the app back to the CPU path.
    pub fn draw(&self, gl: &glow::Context, pool: &TexPool, frame: &GpuTex) -> bool {
        let mut state = self.state.lock().unwrap();
        if matches!(*state, GlState::Uninit) {
            *state = match self.init(gl, pool) {
                Ok(r) => GlState::Ready(r),
                Err(e) => {
                    eprintln!("GPU_PRESENT unavailable, falling back to CPU preview: {e:#}");
                    GlState::Failed
                }
            };
        }
        // キャンバス形式の切替でフレーム寸法が変わった: 旧寸法の interop リソースを
        // 解放して同じ GL コンテキスト上で作り直す。判定は「これから描くフレーム」の
        // 寸法と比べる — プール基準にすると、新プールへ切替わった直後も UI が
        // まだ持っている旧寸法フレームを描けず一瞬黒が出る。
        if matches!(&*state, GlState::Ready(r) if r.w != frame.w || r.h != frame.h) {
            if let GlState::Ready(r) = std::mem::replace(&mut *state, GlState::Uninit) {
                unsafe {
                    (r.funcs.unregister_object)(r.hdev.0, r.hobj.0);
                    gl.delete_texture(r.gname);
                    gl.delete_vertex_array(r.vao);
                    gl.delete_program(r.program);
                }
            }
            eprintln!("GPU_PRESENT reinit for canvas resize -> {}x{}", pool.w, pool.h);
            *state = match self.init(gl, pool) {
                Ok(r) => GlState::Ready(r),
                Err(e) => {
                    eprintln!("GPU_PRESENT re-init after canvas resize failed: {e:#}");
                    GlState::Failed
                }
            };
        }
        let GlState::Ready(ready) = &mut *state else { return false };

        unsafe {
            if ready.shown_id != frame.id {
                // engine device: frame -> shared (under the keyed mutex). The engine
                // context is multithread-protected, so this is safe next to the
                // media thread's own submissions.
                if ready.km1.AcquireSync(0, 8).is_ok() {
                    ready.ctx1.CopyResource(&ready.shared1, &frame.tex);
                    let _ = ready.km1.ReleaseSync(0);
                    ready.ctx1.Flush();
                    // presentation device: shared -> local present texture. GL only
                    // ever sees THIS device, on THIS thread.
                    if ready.km2.AcquireSync(0, 8).is_ok() {
                        ready.ctx2.CopyResource(&ready.present, &ready.shared2);
                        let _ = ready.km2.ReleaseSync(0);
                        ready.ctx2.Flush();
                        ready.shown_id = frame.id;
                    }
                }
                // on a mutex timeout: keep drawing the previous present content and
                // retry the copy on the next repaint
            }
            let mut h = ready.hobj.0;
            if (ready.funcs.lock_objects)(ready.hdev.0, 1, &mut h) == 0 {
                eprintln!(
                    "GPU_PRESENT lock failed ({:?}) — CPU fallback",
                    windows::Win32::Foundation::GetLastError()
                );
                return self.fail(state);
            }
            // The frame is opaque; blending with stale framebuffer alpha is never
            // wanted. egui_glow restores its own state right after this callback.
            gl.disable(glow::BLEND);
            gl.use_program(Some(ready.program));
            gl.bind_vertex_array(Some(ready.vao));
            gl.active_texture(glow::TEXTURE0);
            gl.bind_texture(glow::TEXTURE_2D, Some(ready.gname));
            gl.draw_arrays(glow::TRIANGLE_STRIP, 0, 4);
            gl.bind_texture(glow::TEXTURE_2D, None);
            gl.bind_vertex_array(None);
            gl.use_program(None);
            (ready.funcs.unlock_objects)(ready.hdev.0, 1, &mut h);
        }
        true
    }

    fn fail(&self, mut state: std::sync::MutexGuard<'_, GlState>) -> bool {
        if !self.logged_fail.swap(true, Ordering::Relaxed) {
            eprintln!("GPU_PRESENT disabled after runtime failure");
        }
        *state = GlState::Failed;
        false
    }
}
