// PoC-2 (overlay-surface mode): native GES video composited over a WebView2 preview region.
// The GES player lets d3d11videosink create its OWN window (class GSTD3D11) -- that path renders
// video reliably. This shell finds that window, strips its border, makes it top-most, and keeps
// it aligned (screen coords) to the preview <div> reported by the webview via IPC.

use std::cell::Cell;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};
use std::time::Duration;

use serde::Deserialize;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::window::WindowBuilder;
use wry::WebViewBuilder;

#[link(name = "user32")]
extern "system" {
    fn FindWindowW(class_name: *const u16, window_name: *const u16) -> isize;
    fn SetWindowPos(hwnd: isize, after: isize, x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
    fn SetWindowLongPtrW(hwnd: isize, index: i32, new_long: isize) -> isize;
}
const HWND_TOPMOST: isize = -1;
const GWL_STYLE: i32 = -16;
const WS_POPUP: isize = 0x8000_0000;
const WS_VISIBLE: isize = 0x1000_0000;
const SWP_NOMOVE: u32 = 0x0002;
const SWP_NOSIZE: u32 = 0x0001;
const SWP_NOZORDER: u32 = 0x0004;
const SWP_NOACTIVATE: u32 = 0x0010;
const SWP_SHOWWINDOW: u32 = 0x0040;
const SWP_FRAMECHANGED: u32 = 0x0020;

fn w16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

#[derive(Debug, Deserialize, Clone, Copy)]
struct Rect { x: i32, y: i32, w: i32, h: i32 }

enum UserEvent { Rect(Rect) }

const SINK_CLASS: &str = "GSTD3D11"; // window class d3d11videosink creates

const HTML: &str = r#"
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:#1e1e22;color:#ddd;font-family:Segoe UI,system-ui;overflow:hidden}
  .app{display:flex;flex-direction:column;height:100%}
  .top{height:48px;background:#2b2b32;display:flex;align-items:center;padding:0 14px;gap:10px;border-bottom:1px solid #000}
  .dot{width:10px;height:10px;border-radius:50%;background:#e0564b}
  .body{flex:1;display:flex;min-height:0}
  .side{width:220px;background:#26262c;border-right:1px solid #000;padding:10px;font-size:12px;color:#9aa}
  .stage{flex:1;display:flex;align-items:center;justify-content:center;padding:18px}
  #preview{aspect-ratio:9/16;height:92%;max-width:96%;background:#000;border:2px solid #3a86ff;border-radius:8px;
           box-shadow:0 0 0 3px rgba(58,134,255,.25)}
</style></head><body>
<div class="app">
  <div class="top"><span class="dot"></span><b>Production — PoC-2 overlay</b>
     <span style="color:#789;font-size:12px">ネイティブGES映像が青枠に追従（移動/リサイズで確認）</span></div>
  <div class="body">
    <div class="side">素材パネル（ダミー）<br><br>UI=WebView2。<br>青枠=プレビュー枠。<br>映像はwebviewの外＝ネイティブ面。</div>
    <div class="stage"><div id="preview"></div></div>
  </div>
</div>
<script>
  function report(){
    const r = document.getElementById('preview').getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    window.ipc.postMessage(JSON.stringify({x:Math.round(r.left*dpr), y:Math.round(r.top*dpr),
                                           w:Math.round(r.width*dpr), h:Math.round(r.height*dpr)}));
  }
  window.addEventListener('resize', report);
  new ResizeObserver(report).observe(document.getElementById('preview'));
  window.addEventListener('load', ()=>{ report(); setInterval(report, 150); });
</script>
</body></html>
"#;

fn spawn_player() -> Option<Child> {
    let py39 = std::env::var("POC2_PY39").expect("POC2_PY39");
    let script = std::env::var("POC2_SCRIPT").expect("POC2_SCRIPT");
    let content = std::env::var("POC2_CONTENT").expect("POC2_CONTENT");
    let assets = std::env::var("POC2_ASSETS").expect("POC2_ASSETS");
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    match Command::new(&py39).arg(&script).arg(&content).arg(&assets)
        .creation_flags(CREATE_NO_WINDOW).spawn()
    {
        Ok(c) => { eprintln!("[shell] spawned GES player"); Some(c) }
        Err(e) => { eprintln!("[shell] FAILED to spawn player: {}", e); None }
    }
}

fn find_sink_window() -> isize {
    let class = w16(SINK_CLASS);
    unsafe { FindWindowW(class.as_ptr(), std::ptr::null()) }
}

fn make_borderless(hwnd: isize) {
    unsafe {
        SetWindowLongPtrW(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
        SetWindowPos(hwnd, 0, 0, 0, 0, 0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    }
}

fn main() -> wry::Result<()> {
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    let window = WindowBuilder::new()
        .with_title("Production — PoC-2 (native GES overlay on WebView2)")
        .with_inner_size(tao::dpi::LogicalSize::new(1280.0, 820.0))
        .build(&event_loop)
        .unwrap();

    let _webview = WebViewBuilder::new()
        .with_html(HTML)
        .with_ipc_handler(move |req: wry::http::Request<String>| {
            if let Ok(r) = serde_json::from_str::<Rect>(req.body()) {
                let _ = proxy.send_event(UserEvent::Rect(r));
            }
        })
        .build(&window)?;

    let mut player = spawn_player();

    // Wait for d3d11videosink's own window, then strip its border.
    let mut sink: isize = 0;
    for _ in 0..150 {
        sink = find_sink_window();
        if sink != 0 { break; }
        std::thread::sleep(Duration::from_millis(100));
    }
    if sink != 0 {
        eprintln!("[shell] found sink window {} -> borderless", sink);
        make_borderless(sink);
    } else {
        eprintln!("[shell] sink window (GSTD3D11) not found");
    }

    let last_rect: Cell<Option<Rect>> = Cell::new(None);

    let apply = move |sink: isize, last: &Cell<Option<Rect>>, window: &tao::window::Window| {
        if sink == 0 { return; }
        if let Some(r) = last.get() {
            if let Ok(origin) = window.inner_position() {
                unsafe {
                    SetWindowPos(sink, HWND_TOPMOST, origin.x + r.x, origin.y + r.y, r.w, r.h,
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
                }
            }
        }
    };

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::Rect(r)) => {
                last_rect.set(Some(r));
                apply(sink, &last_rect, &window);
            }
            Event::WindowEvent { event: WindowEvent::Moved(_), .. }
            | Event::WindowEvent { event: WindowEvent::Resized(_), .. } => {
                apply(sink, &last_rect, &window);
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                if let Some(mut c) = player.take() { let _ = c.kill(); }
                *control_flow = ControlFlow::Exit;
            }
            _ => {}
        }
    });
    Ok(())
}
