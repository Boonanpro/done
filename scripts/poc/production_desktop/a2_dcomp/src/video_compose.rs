// A2 step3: REAL GES video composited into the DComp visual under the composition WebView2.
// The A1 engine plays the room timeline with video-sink = d3d12swapchainsink ("DXGI composition
// swapchain sink"). We read the sink's `swapchain` pointer, SetContent it on the DComp video
// visual (below the webview), resize it to a preview-box size, and play.
//
// Result vs step2: the stage shows ACTUAL decoded frames instead of a flat magenta fill.
// (Pixel-exact alignment to the #preview box is step4 via IPC; here the box is fixed.)

use std::cell::RefCell;
use std::rc::Rc;

use windows::core::{Interface, PCWSTR};
use windows::Win32::Foundation::{HINSTANCE, HMODULE, HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows::Win32::Graphics::Direct3D::{D3D_DRIVER_TYPE_HARDWARE, D3D_FEATURE_LEVEL};
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
    D3D11_SDK_VERSION,
};
use windows::Win32::Graphics::DirectComposition::{
    DCompositionCreateDevice, IDCompositionDevice, IDCompositionTarget, IDCompositionVisual,
};
use windows::Win32::Graphics::Dxgi::{IDXGIAdapter, IDXGIDevice, IDXGISwapChain};
use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetClientRect, GetMessageW, PostQuitMessage,
    RegisterClassW, TranslateMessage, CW_USEDEFAULT, MSG, WINDOW_EX_STYLE, WM_DESTROY, WNDCLASSW,
    WS_OVERLAPPEDWINDOW, WS_VISIBLE,
};

use webview2_com::Microsoft::Web::WebView2::Win32::{
    CreateCoreWebView2EnvironmentWithOptions, ICoreWebView2CompositionController,
    ICoreWebView2Controller, ICoreWebView2Controller2, ICoreWebView2Environment,
    ICoreWebView2Environment3, COREWEBVIEW2_COLOR,
};
use webview2_com::{
    CreateCoreWebView2CompositionControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler,
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

const HTML: &str = r#"
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:transparent;color:#ddd;font-family:Segoe UI,system-ui;overflow:hidden}
  .app{display:flex;flex-direction:column;height:100%}
  .top{height:48px;background:#2b2b32;display:flex;align-items:center;padding:0 14px;gap:10px;border-bottom:1px solid #000}
  .dot{width:10px;height:10px;border-radius:50%;background:#e0564b}
  .body{flex:1;display:flex;min-height:0;background:transparent}
  .side{width:220px;background:#26262c;border-right:1px solid #000;padding:10px;font-size:12px;color:#9aa}
  .stage{flex:1;background:transparent}
</style></head><body>
<div class="app">
  <div class="top"><span class="dot"></span><b>Production — A2 step3 (native GES video)</b>
     <span style="color:#789;font-size:12px">stage に本物の編集タイムライン映像が合成（別ウィンドウ無し）</span></div>
  <div class="body">
    <div class="side">素材パネル（ダミー）<br><br>UI=WebView2(composition)。<br>下層=GES d3d12swapchainsink の実映像。</div>
    <div class="stage"></div>
  </div>
</div>
</body></html>
"#;

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe {
        match msg {
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
        let class_name = windows::core::w!("A2VideoCompose");
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
            windows::core::w!("A2 step3 — native GES video over DComp"),
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
        root.AddVisual(&video_visual, false, None)?;
        root.AddVisual(&webview_visual, true, &video_visual)?; // webview above video
        target.SetRoot(&root)?;
        dcomp.Commit()?;

        // ---- GES engine playing the real timeline into a d3d12swapchainsink ----
        Engine::init()?;
        let sink = gst::ElementFactory::make("d3d12swapchainsink")
            .build()
            .map_err(|e| anyhow::anyhow!("make d3d12swapchainsink: {e}"))?;
        let mut engine = Engine::new_with_video_sink(1080, 1920, 30, Some(sink.clone()))?;
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
        controller2.SetDefaultBackgroundColor(COREWEBVIEW2_COLOR { A: 0, R: 0, G: 0, B: 0 })?;
        let mut client = RECT::default();
        GetClientRect(hwnd, &mut client)?;
        controller.SetBounds(client)?;
        controller.SetIsVisible(true)?;
        let webview = controller.CoreWebView2()?;
        let html = wide(HTML);
        webview.NavigateToString(PCWSTR(html.as_ptr()))?;
        dcomp.Commit()?;

        eprintln!("[a2-step3] composition WebView2 up; engine playing real timeline");

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        engine.set_null();
        Ok(())
    }
}
