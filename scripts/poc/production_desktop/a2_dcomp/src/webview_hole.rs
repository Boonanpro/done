// A2 step2: composition-mode WebView2 over a DComp video layer, in ONE window.
// Proves acceptance ①③: the native video composites *through* the transparent webview regions
// and is occluded by the opaque webview chrome — with NO separate window (the PoC-2 "貼り付け"
// airspace defect is gone by construction). VERIFIED via screenshot.
//
// Tree (bottom→top): root visual
//   ├ color visual   : magenta composition swapchain (stands in for GES video; step3 swaps it)
//   └ webview visual : WebView2 composition controller (opaque chrome, transparent body/stage)
//
// Two findings that matter:
//  - DComp AddVisual z-order: with a NULL reference, insertAbove=TRUE adds to the FRONT of the
//    child list (= bottom). To put the webview above the video, reference it explicitly.
//  - Transparency is ancestry-wide: a region reveals the video only if it AND every ancestor up
//    to <html> is transparent. One opaque ancestor (e.g. .body) blocks the video.
//  - DPI: the app is per-monitor-DPI-aware (physical px) but WebView2 lays out in CSS px, so the
//    #preview rect must reach the engine as getBoundingClientRect()*devicePixelRatio (step4 IPC).
//
// Self-verify: screenshot; expect magenta (video) in the transparent stage AND opaque dark
// chrome (header + side panel) composited on top.

use std::cell::RefCell;
use std::rc::Rc;

use windows::core::{Interface, PCWSTR};
use windows::Win32::Foundation::{HINSTANCE, HMODULE, HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows::Win32::Graphics::Direct3D::{D3D_DRIVER_TYPE_HARDWARE, D3D_FEATURE_LEVEL};
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, ID3D11RenderTargetView,
    ID3D11Texture2D, D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_SDK_VERSION,
};
use windows::Win32::Graphics::DirectComposition::{
    DCompositionCreateDevice, IDCompositionDevice, IDCompositionTarget, IDCompositionVisual,
};
use windows::Win32::Graphics::Dxgi::Common::{
    DXGI_ALPHA_MODE_IGNORE, DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC,
};
use windows::Win32::Graphics::Dxgi::{
    IDXGIAdapter, IDXGIDevice, IDXGIFactory2, IDXGISwapChain1, DXGI_SCALING_STRETCH, DXGI_SWAP_CHAIN_DESC1,
    DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL, DXGI_USAGE_RENDER_TARGET_OUTPUT,
};
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

// magenta video stand-in. Large here to fill the preview/stage region; step3 swaps it for the
// GES d3d12swapchainsink, and step4 sizes/positions it to the IPC-reported preview rect
// (device px = getBoundingClientRect()*devicePixelRatio — needed because the app is
// per-monitor-DPI-aware while WebView2 lays out in CSS px).
const CX: f32 = 40.0;
const CY: f32 = 30.0;
const CW: u32 = 1180;
const CH: u32 = 740;
const COLOR: [f32; 4] = [1.0, 0.125, 0.78, 1.0]; // R255 G32 B199

const HTML: &str = r#"
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:transparent;color:#fff;font-family:Segoe UI,system-ui;overflow:hidden}
  .app{display:flex;flex-direction:column;height:100%}
  /* OPAQUE chrome (covers the video); TRANSPARENT body/stage (video shows through). For a
     region to reveal the native video, it AND all its ancestors up to <html> must be transparent. */
  .top{height:48px;background:#2b2b32;display:flex;align-items:center;padding:0 14px;gap:10px;border-bottom:1px solid #000}
  .dot{width:10px;height:10px;border-radius:50%;background:#e0564b}
  .body{flex:1;display:flex;min-height:0;background:transparent}
  .side{width:220px;background:#26262c;border-right:1px solid #000;padding:10px;font-size:12px;color:#9aa}
  /* stage TRANSPARENT so the native video layer below shows through; webview UI (top bar +
     side panel) stays opaque and composites ON TOP of the video — one window, no airspace.
     step4 makes the stage opaque and clips video to the #preview rect via IPC. */
  .stage{flex:1;display:flex;align-items:center;justify-content:center;padding:18px;background:transparent}
  #preview{aspect-ratio:9/16;height:88%;max-width:96%;background:transparent;border:3px solid #3a86ff;border-radius:8px}
</style></head><body>
<div class="app">
  <div class="top"><span class="dot"></span><b>Production — A2 step2 (composition WebView2)</b>
     <span style="color:#789;font-size:12px">青枠=透明な穴。下のネイティブ映像が透ける（別ウィンドウ無し）</span></div>
  <div class="body">
    <div class="side">素材パネル（ダミー）<br><br>UI=WebView2(composition)。<br>#preview を transparent にして穴を空け、<br>DComp の下層映像を透かす。</div>
    <div class="stage"><div id="preview"></div></div>
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

        let hmodule = GetModuleHandleW(None)?;
        let hinst = HINSTANCE(hmodule.0);
        let class_name = windows::core::w!("A2WebViewHole");
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
            windows::core::w!("A2 step2 — composition WebView2 over DComp video"),
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

        // ---- D3D11 device ----
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
        let context = context.unwrap();
        let dxgi_device: IDXGIDevice = device.cast()?;
        let factory: IDXGIFactory2 = dxgi_device.GetAdapter()?.GetParent()?;

        // ---- magenta composition swapchain (video stand-in) ----
        let desc = DXGI_SWAP_CHAIN_DESC1 {
            Width: CW,
            Height: CH,
            Format: DXGI_FORMAT_B8G8R8A8_UNORM,
            Stereo: false.into(),
            SampleDesc: DXGI_SAMPLE_DESC { Count: 1, Quality: 0 },
            BufferUsage: DXGI_USAGE_RENDER_TARGET_OUTPUT,
            BufferCount: 2,
            Scaling: DXGI_SCALING_STRETCH,
            SwapEffect: DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL,
            AlphaMode: DXGI_ALPHA_MODE_IGNORE,
            Flags: 0,
        };
        let swapchain: IDXGISwapChain1 =
            factory.CreateSwapChainForComposition(&device, &desc, None)?;
        let backbuf: ID3D11Texture2D = swapchain.GetBuffer(0)?;
        let mut rtv: Option<ID3D11RenderTargetView> = None;
        device.CreateRenderTargetView(&backbuf, None, Some(&mut rtv))?;
        context.ClearRenderTargetView(&rtv.unwrap(), &COLOR);
        swapchain.Present(1, Default::default()).ok()?;

        // ---- DComp tree: root → [color visual] (bottom), [webview visual] (top) ----
        let dcomp: IDCompositionDevice = DCompositionCreateDevice(&dxgi_device)?;
        let target: IDCompositionTarget = dcomp.CreateTargetForHwnd(hwnd, true)?;
        let root: IDCompositionVisual = dcomp.CreateVisual()?;

        let color_visual: IDCompositionVisual = dcomp.CreateVisual()?;
        color_visual.SetContent(&swapchain)?;
        color_visual.SetOffsetX2(CX)?;
        color_visual.SetOffsetY2(CY)?;

        let webview_visual: IDCompositionVisual = dcomp.CreateVisual()?;
        webview_visual.SetOffsetX2(0.0)?;
        webview_visual.SetOffsetY2(0.0)?;

        // z-order: video below, webview above. With a NULL reference, AddVisual's insertAbove
        // is inverted (TRUE = front of list = bottom), so reference webview explicitly ABOVE color.
        root.AddVisual(&color_visual, false, None)?;
        root.AddVisual(&webview_visual, true, &color_visual)?; // webview in front of video
        target.SetRoot(&root)?;
        dcomp.Commit()?;

        // ---- WebView2 environment (composition) ----
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

        // ---- composition controller ----
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

        // attach the webview to our DComp visual + make it transparent
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

        eprintln!(
            "[a2-step2] composition WebView2 up over magenta layer; client {}x{}",
            client.right, client.bottom
        );

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Ok(())
    }
}
