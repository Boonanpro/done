// PoC-2: native GES video overlaid on a WebView2 preview region (wry + tao).
// The webview reports its preview <div> rect; we keep a native child window (into which
// a separate GES player process renders) aligned to that rect on every resize/scroll.
// This proves the §6 "native overlay surface" geometry-sync premise.

use std::ffi::c_void;
use std::os::windows::process::CommandExt;
use std::process::Command;

use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use serde::Deserialize;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::window::WindowBuilder;
use wry::WebViewBuilder;

// --- minimal Win32 FFI (avoids the churny `windows` crate) ---
#[link(name = "user32")]
extern "system" {
    fn CreateWindowExW(
        ex_style: u32, class_name: *const u16, window_name: *const u16, style: u32,
        x: i32, y: i32, w: i32, h: i32, parent: isize, menu: isize, instance: isize,
        param: *const c_void,
    ) -> isize;
    fn SetWindowPos(hwnd: isize, after: isize, x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
}
const WS_CHILD: u32 = 0x4000_0000;
const WS_VISIBLE: u32 = 0x1000_0000;
const SWP_NOZORDER: u32 = 0x0004;
const SWP_NOACTIVATE: u32 = 0x0010;

fn w16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

#[derive(Debug, Deserialize, Clone, Copy)]
struct Rect { x: i32, y: i32, w: i32, h: i32 }

enum UserEvent { Rect(Rect) }

const HTML: &str = r#"
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:#1e1e22;color:#ddd;font-family:Segoe UI,system-ui;overflow:hidden}
  .app{display:flex;flex-direction:column;height:100%}
  .top{height:48px;background:#2b2b32;display:flex;align-items:center;padding:0 14px;gap:10px;border-bottom:1px solid #000}
  .dot{width:10px;height:10px;border-radius:50%;background:#e0564b}
  .body{flex:1;display:flex;min-height:0}
  .side{width:220px;background:#26262c;border-right:1px solid #000;padding:10px;font-size:12px;color:#9aa}
  .stage{flex:1;display:flex;align-items:center;justify-content:center;padding:18px}
  /* the preview region the native video must track */
  #preview{aspect-ratio:9/16;height:92%;max-width:96%;background:#000;border:2px solid #3a86ff;border-radius:8px;
           box-shadow:0 0 0 3px rgba(58,134,255,.25)}
  .hint{position:absolute;bottom:10px;left:50%;transform:translateX(-50%);font-size:12px;color:#789;opacity:.8}
</style></head><body>
<div class="app">
  <div class="top"><span class="dot"></span><b>Production — PoC-2 overlay</b>
     <span style="color:#789;font-size:12px">ネイティブGES映像が青枠に追従します（ウィンドウをリサイズして確認）</span></div>
  <div class="body">
    <div class="side">素材パネル（ダミー）<br><br>このReact相当UIはWebView2。<br>青枠＝プレビュー枠。<br>映像はwebviewの外＝ネイティブ。</div>
    <div class="stage"><div id="preview"></div></div>
  </div>
</div>
<div class="hint">native video is a child HWND composited over the webview, kept aligned via IPC</div>
<script>
  function report(){
    const r = document.getElementById('preview').getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const msg = {x:Math.round(r.left*dpr), y:Math.round(r.top*dpr),
                 w:Math.round(r.width*dpr), h:Math.round(r.height*dpr)};
    window.ipc.postMessage(JSON.stringify(msg));
  }
  window.addEventListener('resize', report);
  new ResizeObserver(report).observe(document.getElementById('preview'));
  window.addEventListener('load', ()=>{ report(); setInterval(report, 300); });
</script>
</body></html>
"#;

fn hwnd_of(window: &tao::window::Window) -> isize {
    match window.window_handle().unwrap().as_raw() {
        RawWindowHandle::Win32(h) => h.hwnd.get(),
        _ => panic!("not win32"),
    }
}

fn spawn_player(child_hwnd: isize) {
    let py39 = std::env::var("POC2_PY39").expect("POC2_PY39");
    let script = std::env::var("POC2_SCRIPT").expect("POC2_SCRIPT");
    let content = std::env::var("POC2_CONTENT").expect("POC2_CONTENT");
    let assets = std::env::var("POC2_ASSETS").expect("POC2_ASSETS");
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    match Command::new(&py39)
        .arg(&script).arg(&content).arg(&assets)
        .arg("--hwnd").arg(child_hwnd.to_string())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
    {
        Ok(_) => eprintln!("[shell] spawned GES player into hwnd {}", child_hwnd),
        Err(e) => eprintln!("[shell] FAILED to spawn player: {}", e),
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

    let parent = hwnd_of(&window);

    // Build the webview first so the overlay child window sits ABOVE it in z-order.
    let _webview = WebViewBuilder::new()
        .with_html(HTML)
        .with_ipc_handler(move |req: wry::http::Request<String>| {
            if let Ok(r) = serde_json::from_str::<Rect>(req.body()) {
                let _ = proxy.send_event(UserEvent::Rect(r));
            }
        })
        .build(&window)?;

    // Native child window the GES player renders into.
    let class = w16("STATIC");
    let name = w16("");
    let child = unsafe {
        CreateWindowExW(0, class.as_ptr(), name.as_ptr(),
            WS_CHILD | WS_VISIBLE, 0, 0, 320, 180, parent, 0, 0, std::ptr::null())
    };
    if child == 0 {
        eprintln!("[shell] CreateWindowExW failed");
    }
    spawn_player(child);

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::Rect(r)) => unsafe {
                SetWindowPos(child, 0, r.x, r.y, r.w, r.h, SWP_NOZORDER | SWP_NOACTIVATE);
            },
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                *control_flow = ControlFlow::Exit;
            }
            _ => {}
        }
    });
    Ok(())
}
