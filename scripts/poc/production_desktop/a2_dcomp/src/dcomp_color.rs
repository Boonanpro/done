// A2 step1: prove in-process DirectComposition compositing.
// A single Win32 window hosts a DComp visual tree whose one visual's content is a
// **composition swapchain** (the same mechanism GES's d3d12swapchainsink uses) cleared to a
// distinctive magenta. If a magenta rectangle appears in the window, DComp compositing works
// in-process — the foundation for the WebView2 visual (transparent hole) + GES video visual.
//
// Self-verify: launch headless-ish, screenshot the screen, look for the magenta blob.

use windows::core::{w, Interface, Result};
use windows::Win32::Foundation::{HINSTANCE, HMODULE, HWND, LPARAM, LRESULT, WPARAM};
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
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, PostQuitMessage,
    RegisterClassW, TranslateMessage, CW_USEDEFAULT, MSG, WINDOW_EX_STYLE, WNDCLASSW,
    WS_OVERLAPPEDWINDOW, WS_VISIBLE, WM_DESTROY,
};

// The visual rectangle (device pixels) and its distinctive color.
const VX: f32 = 220.0;
const VY: f32 = 160.0;
const VW: u32 = 480;
const VH: u32 = 360;
// magenta (B8G8R8A8 cleared via RGBA floats): R=1.0 G=0.125 B=0.78
const COLOR: [f32; 4] = [1.0, 0.125, 0.78, 1.0];

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

fn main() -> Result<()> {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);

        let hmodule = GetModuleHandleW(None)?;
        let hinst = HINSTANCE(hmodule.0);
        let class_name = w!("A2DCompColor");
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
            w!("A2 step1 — DComp color swapchain"),
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

        // ---- D3D11 device (BGRA for composition) ----
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

        // ---- DXGI factory from the device ----
        let dxgi_device: IDXGIDevice = device.cast()?;
        let adapter = dxgi_device.GetAdapter()?;
        let factory: IDXGIFactory2 = adapter.GetParent()?;

        // ---- composition swapchain (no HWND) ----
        let desc = DXGI_SWAP_CHAIN_DESC1 {
            Width: VW,
            Height: VH,
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

        // clear the backbuffer to magenta and present
        let backbuf: ID3D11Texture2D = swapchain.GetBuffer(0)?;
        let mut rtv: Option<ID3D11RenderTargetView> = None;
        device.CreateRenderTargetView(&backbuf, None, Some(&mut rtv))?;
        let rtv = rtv.unwrap();
        context.ClearRenderTargetView(&rtv, &COLOR);
        swapchain.Present(1, Default::default()).ok()?;

        // ---- DComp device/target/visual ----
        let dcomp: IDCompositionDevice = DCompositionCreateDevice(&dxgi_device)?;

        let target: IDCompositionTarget = dcomp.CreateTargetForHwnd(hwnd, true)?;
        let visual: IDCompositionVisual = dcomp.CreateVisual()?;
        visual.SetContent(&swapchain)?;
        visual.SetOffsetX2(VX)?;
        visual.SetOffsetY2(VY)?;
        target.SetRoot(&visual)?;
        dcomp.Commit()?;

        eprintln!(
            "[a2-step1] window up; magenta swapchain visual at ({},{}) {}x{}",
            VX as i32, VY as i32, VW, VH
        );

        // ---- message loop ----
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Ok(())
    }
}
