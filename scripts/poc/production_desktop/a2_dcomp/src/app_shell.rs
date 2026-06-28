// A3 (look-first): desktop shell loads the REAL Next.js production UI over HTTP into the
// The A1 engine plays the room timeline with video-sink = d3d12swapchainsink ("DXGI composition
// swapchain sink"). We read the sink's `swapchain` pointer, SetContent it on the DComp video
// visual (below the webview), resize it to a preview-box size, and play.
//
// Result vs step2: the stage shows ACTUAL decoded frames instead of a flat magenta fill.
// (Pixel-exact alignment to the #preview box is step4 via IPC; here the box is fixed.)

use std::cell::RefCell;
use std::rc::Rc;

use windows::core::{Interface, PCWSTR, PWSTR};
use windows::Win32::Foundation::{HINSTANCE, HMODULE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::Graphics::Direct3D::{D3D_DRIVER_TYPE_HARDWARE, D3D_FEATURE_LEVEL};
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
    D3D11_SDK_VERSION,
};
use windows::Win32::Graphics::DirectComposition::{
    DCompositionCreateDevice, IDCompositionDevice, IDCompositionTarget, IDCompositionVisual,
};
use windows::Win32::Graphics::Dxgi::{IDXGIAdapter, IDXGIDevice, IDXGISwapChain};
use windows::Win32::System::Com::{CoInitializeEx, CoTaskMemFree, COINIT_APARTMENTTHREADED};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::WinRT::EventRegistrationToken;
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetClientRect, GetMessageW,
    GetWindowLongPtrW, PostQuitMessage, RegisterClassW, SetWindowLongPtrW, TranslateMessage,
    CW_USEDEFAULT, GWLP_USERDATA, MSG, WINDOW_EX_STYLE, WM_DESTROY, WM_KEYDOWN, WM_LBUTTONDOWN,
    WM_LBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEMOVE, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_SIZE,
    WNDCLASSW,
    WS_OVERLAPPEDWINDOW, WS_VISIBLE,
};

use webview2_com::Microsoft::Web::WebView2::Win32::{
    CreateCoreWebView2EnvironmentWithOptions, ICoreWebView2, ICoreWebView2CompositionController,
    ICoreWebView2Controller, ICoreWebView2Controller2, ICoreWebView2Environment,
    ICoreWebView2Environment3, ICoreWebView2WebMessageReceivedEventArgs, COREWEBVIEW2_COLOR,
    COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_DOWN, COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_UP,
    COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_DOWN, COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_UP,
    COREWEBVIEW2_MOUSE_EVENT_KIND_MOVE, COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_DOWN,
    COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_UP, COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS,
};
use webview2_com::{
    CreateCoreWebView2CompositionControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler, WebMessageReceivedEventHandler,
};

use a1_engine::Engine;
use gstreamer as gst;
use gstreamer::glib;
use gstreamer::glib::translate::ToGlibPtr;
use gstreamer::prelude::*;

// the real room timeline + proxies (live under D:\done, gitignored)
const ROOM: &str = "D:/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1";
// video box (device px) — fixed for step3; step4 drives it from the #preview rect via IPC
const BX: f32 = 360.0;
const BY: f32 = 120.0;
const BW: u32 = 420;
const BH: u32 = 600;

const URL: &str = "http://localhost:3000/scratch/desktop-demo";

/// Parse {"x":N,"y":N,"w":N,"h":N} (integers) from the IPC message — no serde dependency.
fn parse_rect(s: &str) -> Option<(i32, i32, u32, u32)> {
    fn field(s: &str, key: &str) -> Option<i64> {
        let i = s.find(&format!("\"{key}\""))?;
        let rest = &s[i + key.len() + 2..];
        let colon = rest.find(':')?;
        let after = rest[colon + 1..].trim_start();
        let end = after
            .find(|c: char| !(c.is_ascii_digit() || c == '-'))
            .unwrap_or(after.len());
        after[..end].parse::<i64>().ok()
    }
    let x = field(s, "x")? as i32;
    let y = field(s, "y")? as i32;
    let w = field(s, "w")?.max(1) as u32;
    let h = field(s, "h")?.max(1) as u32;
    Some((x, y, w, h))
}

/// Parse a transport command {"cmd":"play"|"pause"|"seek","pos":N} from the IPC message.
fn parse_cmd(s: &str) -> Option<(String, f64)> {
    let ci = s.find("\"cmd\"")?;
    let after = &s[ci + 5..];
    let q1 = after.find('"')?;
    let rest = &after[q1 + 1..];
    let q2 = rest.find('"')?;
    let cmd = rest[..q2].to_string();
    let pos = (|| {
        let pi = s.find("\"pos\"")?;
        let r = &s[pi + 5..];
        let c = r.find(':')?;
        let a = r[c + 1..].trim_start();
        let end = a
            .find(|ch: char| !(ch.is_ascii_digit() || ch == '-' || ch == '.'))
            .unwrap_or(a.len());
        a[..end].parse::<f64>().ok()
    })()
    .unwrap_or(0.0);
    Some((cmd, pos))
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// Stashed in the window's USERDATA so `wndproc` can reflow the webview (WM_SIZE) and forward
/// mouse input to it (composition-hosted WebView2 does NOT get input automatically).
struct WndState {
    controller: ICoreWebView2Controller,
    comp_controller: ICoreWebView2CompositionController,
    webview: ICoreWebView2,
    dcomp: IDCompositionDevice,
}

extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe {
        match msg {
            WM_SIZE => {
                // window resized → update the webview bounds so the UI reflows; the page then
                // re-reports its #preview rect (IPC) and the video re-aligns.
                let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const WndState;
                if !ptr.is_null() {
                    let st = &*ptr;
                    let mut rc = RECT::default();
                    if GetClientRect(hwnd, &mut rc).is_ok() {
                        let _ = st.controller.SetBounds(rc);
                        let _ = st.dcomp.Commit();
                    }
                }
                LRESULT(0)
            }
            WM_MOUSEMOVE | WM_LBUTTONDOWN | WM_LBUTTONUP | WM_RBUTTONDOWN | WM_RBUTTONUP
            | WM_MBUTTONDOWN | WM_MBUTTONUP => {
                // forward mouse input to the composition-hosted webview (else the UI is inert)
                let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const WndState;
                if !ptr.is_null() {
                    let st = &*ptr;
                    let kind = match msg {
                        WM_MOUSEMOVE => COREWEBVIEW2_MOUSE_EVENT_KIND_MOVE,
                        WM_LBUTTONDOWN => COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_DOWN,
                        WM_LBUTTONUP => COREWEBVIEW2_MOUSE_EVENT_KIND_LEFT_BUTTON_UP,
                        WM_RBUTTONDOWN => COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_DOWN,
                        WM_RBUTTONUP => COREWEBVIEW2_MOUSE_EVENT_KIND_RIGHT_BUTTON_UP,
                        WM_MBUTTONDOWN => COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_DOWN,
                        _ => COREWEBVIEW2_MOUSE_EVENT_KIND_MIDDLE_BUTTON_UP,
                    };
                    let x = (lp.0 & 0xFFFF) as i16 as i32;
                    let y = ((lp.0 >> 16) & 0xFFFF) as i16 as i32;
                    let vkeys = COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS((wp.0 & 0xFFFF) as i32);
                    let _ = st
                        .comp_controller
                        .SendMouseInput(kind, vkeys, 0, POINT { x, y });
                }
                LRESULT(0)
            }
            WM_KEYDOWN => {
                // composition webview doesn't get keyboard focus by default → relay Space to the
                // page so its spacebar play/pause handler fires.
                if (wp.0 & 0xFFFF) == 0x20 {
                    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const WndState;
                    if !ptr.is_null() {
                        let st = &*ptr;
                        let m = wide("space");
                        let _ = st.webview.PostWebMessageAsString(PCWSTR(m.as_ptr()));
                    }
                    LRESULT(0)
                } else {
                    DefWindowProcW(hwnd, msg, wp, lp)
                }
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                LRESULT(0)
            }
            _ => DefWindowProcW(hwnd, msg, wp, lp),
        }
    }
}

fn wv_err<E: std::fmt::Debug>(e: E) -> anyhow::Error {
    anyhow::anyhow!("{e:?}")
}

fn main() -> anyhow::Result<()> {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok()?;

        // ---- window ----
        let hmodule = GetModuleHandleW(None)?;
        let hinst = HINSTANCE(hmodule.0);
        let class_name = windows::core::w!("A3AppShell");
        let wc = WNDCLASSW {
            lpfnWndProc: Some(wndproc),
            hInstance: hinst,
            lpszClassName: class_name,
            ..Default::default()
        };
        RegisterClassW(&wc);
        let hwnd = CreateWindowExW(
            WINDOW_EX_STYLE(0),
            class_name,
            windows::core::w!("A3 — production UI desktop shell"),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            1280,
            820,
            None,
            None,
            hinst,
            None,
        )?;

        // ---- D3D11 device just for the DComp device ----
        let mut device: Option<ID3D11Device> = None;
        let mut context: Option<ID3D11DeviceContext> = None;
        let mut flevel = D3D_FEATURE_LEVEL::default();
        D3D11CreateDevice(
            Option::<&IDXGIAdapter>::None,
            D3D_DRIVER_TYPE_HARDWARE,
            HMODULE::default(),
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            None,
            D3D11_SDK_VERSION,
            Some(&mut device),
            Some(&mut flevel),
            Some(&mut context),
        )?;
        let device = device.unwrap();
        let dxgi_device: IDXGIDevice = device.cast()?;

        // ---- DComp tree: video visual (bottom) + webview visual (top) ----
        let dcomp: IDCompositionDevice = DCompositionCreateDevice(&dxgi_device)?;
        let target: IDCompositionTarget = dcomp.CreateTargetForHwnd(hwnd, true)?;
        let root: IDCompositionVisual = dcomp.CreateVisual()?;
        let video_visual: IDCompositionVisual = dcomp.CreateVisual()?;
        video_visual.SetOffsetX2(BX)?;
        video_visual.SetOffsetY2(BY)?;
        let webview_visual: IDCompositionVisual = dcomp.CreateVisual()?;
        webview_visual.SetOffsetX2(0.0)?;
        webview_visual.SetOffsetY2(0.0)?;
        root.AddVisual(&webview_visual, false, None)?;
        root.AddVisual(&video_visual, true, &webview_visual)?; // video above the opaque webview
        target.SetRoot(&root)?;
        dcomp.Commit()?;

        // ---- GES engine playing the real timeline into a d3d12swapchainsink ----
        Engine::init()?;
        let sink = gst::ElementFactory::make("d3d12swapchainsink")
            .build()
            .map_err(|e| anyhow::anyhow!("make d3d12swapchainsink: {e}"))?;
        // real audio output (autoaudiosink → wasapi); falls back to silent if unavailable
        let audio_sink = gst::ElementFactory::make("autoaudiosink").build().ok();
        let mut engine = Engine::new_full(1080, 1920, 30, Some(sink.clone()), audio_sink)?;
        let load = engine.load(&format!("{ROOM}/contents.json"), ROOM)?;
        eprintln!(
            "[a2-step3] timeline loaded: {} video / {} overlay / {} audio, preroll_ok={}",
            load.video_clips, load.overlay_clips, load.audio_clips, load.preroll_ok
        );

        // size the sink's swapchain to the preview box, then bind it to the DComp visual
        sink.emit_by_name::<()>("resize", &[&BW, &BH]);
        let val = sink.property_value("swapchain");
        let stash: glib::translate::Stash<*const glib::gobject_ffi::GValue, glib::Value> =
            val.to_glib_none();
        let raw = glib::gobject_ffi::g_value_get_pointer(stash.0) as *mut core::ffi::c_void;
        if raw.is_null() {
            eprintln!("[a2-step3] WARNING: swapchain pointer null after preroll");
        } else {
            let swapchain: IDXGISwapChain = IDXGISwapChain::from_raw_borrowed(&raw)
                .ok_or_else(|| anyhow::anyhow!("wrap swapchain"))?
                .clone();
            video_visual.SetContent(&swapchain)?;
            dcomp.Commit()?;
            eprintln!("[a2-step3] swapchain bound to DComp video visual ({}x{})", BW, BH);
        }

        // share the engine with the IPC handler (transport commands) — play/pause/seek are &self
        let engine = Rc::new(engine);
        engine.play()?;

        // ---- composition WebView2 on top (opaque chrome, transparent stage) ----
        let mut udata_dir = std::env::temp_dir();
        udata_dir.push("a2_webview_ud");
        let _ = std::fs::create_dir_all(&udata_dir);
        let udata = wide(&udata_dir.to_string_lossy());

        let env_cell: Rc<RefCell<Option<ICoreWebView2Environment>>> = Rc::new(RefCell::new(None));
        {
            let out = env_cell.clone();
            CreateCoreWebView2EnvironmentCompletedHandler::wait_for_async_operation(
                Box::new(move |handler| {
                    CreateCoreWebView2EnvironmentWithOptions(
                        PCWSTR::null(),
                        PCWSTR(udata.as_ptr()),
                        None,
                        &handler,
                    )
                    .map_err(webview2_com::Error::WindowsError)
                }),
                Box::new(move |hr, env| {
                    hr?;
                    *out.borrow_mut() = env;
                    Ok(())
                }),
            )
            .map_err(wv_err)?;
        }
        let environment = env_cell.borrow_mut().take().expect("environment");
        let env3: ICoreWebView2Environment3 = environment.cast()?;

        let ctrl_cell: Rc<RefCell<Option<ICoreWebView2CompositionController>>> =
            Rc::new(RefCell::new(None));
        {
            let out = ctrl_cell.clone();
            let env3 = env3.clone();
            CreateCoreWebView2CompositionControllerCompletedHandler::wait_for_async_operation(
                Box::new(move |handler| {
                    env3.CreateCoreWebView2CompositionController(hwnd, &handler)
                        .map_err(webview2_com::Error::WindowsError)
                }),
                Box::new(move |hr, controller| {
                    hr?;
                    *out.borrow_mut() = controller;
                    Ok(())
                }),
            )
            .map_err(wv_err)?;
        }
        let comp_controller = ctrl_cell.borrow_mut().take().expect("composition controller");

        comp_controller.SetRootVisualTarget(&webview_visual)?;
        let controller: ICoreWebView2Controller = comp_controller.cast()?;
        let controller2: ICoreWebView2Controller2 = comp_controller.cast()?;
        controller2.SetDefaultBackgroundColor(COREWEBVIEW2_COLOR { A: 255, R: 21, G: 21, B: 26 })?;
        let mut client = RECT::default();
        GetClientRect(hwnd, &mut client)?;
        controller.SetBounds(client)?;
        controller.SetIsVisible(true)?;
        let webview = controller.CoreWebView2()?;

        // let wndproc reach the controller (WM_SIZE reflow) + comp controller (mouse input)
        let state = Box::new(WndState {
            controller: controller.clone(),
            comp_controller: comp_controller.clone(),
            webview: webview.clone(),
            dcomp: dcomp.clone(),
        });
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, Box::into_raw(state) as isize);

        // step4: follow the #preview box. JS posts {x,y,w,h} in device px; we resize the sink
        // swapchain to (w,h), rebind it (resize may recreate buffers), and move the video visual
        // to (x,y). This is what makes the native video line up with the webview's preview box
        // across move/resize/DPI/scroll.
        let sink_c = sink.clone();
        let video_c = video_visual.clone();
        let dcomp_c = dcomp.clone();
        let engine_c = engine.clone();
        let handler = WebMessageReceivedEventHandler::create(Box::new(
            move |_wv: Option<ICoreWebView2>,
                  args: Option<ICoreWebView2WebMessageReceivedEventArgs>|
                  -> windows::core::Result<()> {
                if let Some(args) = args {
                    let mut pw = PWSTR::null();
                    unsafe { args.TryGetWebMessageAsString(&mut pw) }?;
                    let s = unsafe { pw.to_string() }.unwrap_or_default();
                    unsafe { CoTaskMemFree(Some(pw.0 as *const core::ffi::c_void)) };
                    if let Some((x, y, w, h)) = parse_rect(&s) {
                        sink_c.emit_by_name::<()>("resize", &[&w, &h]);
                        let val = sink_c.property_value("swapchain");
                        let stash: glib::translate::Stash<
                            *const glib::gobject_ffi::GValue,
                            glib::Value,
                        > = val.to_glib_none();
                        let raw = unsafe { glib::gobject_ffi::g_value_get_pointer(stash.0) }
                            as *mut core::ffi::c_void;
                        unsafe {
                            if !raw.is_null() {
                                if let Some(sc) = IDXGISwapChain::from_raw_borrowed(&raw) {
                                    let _ = video_c.SetContent(&sc.clone());
                                }
                            }
                            let _ = video_c.SetOffsetX2(x as f32);
                            let _ = video_c.SetOffsetY2(y as f32);
                            let _ = dcomp_c.Commit();
                        }
                    } else if let Some((cmd, pos)) = parse_cmd(&s) {
                        // transport: route UI buttons to the engine (play/pause/seek)
                        match cmd.as_str() {
                            "play" => { let _ = engine_c.play(); }
                            "pause" => { let _ = engine_c.pause(); }
                            "seek" => { let _ = engine_c.seek(pos); }
                            _ => {}
                        }
                    }
                }
                Ok(())
            },
        ));
        let mut token = EventRegistrationToken::default();
        webview.add_WebMessageReceived(&handler, &mut token)?;

        let url = wide(URL);
        webview.Navigate(PCWSTR(url.as_ptr()))?;
        dcomp.Commit()?;

        eprintln!("[a3] shell up; loaded Next.js production UI, native video on the preview box");

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        engine.set_null();
        Ok(())
    }
}
