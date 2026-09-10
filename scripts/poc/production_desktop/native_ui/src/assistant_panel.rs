//! Embedded conversation: the microphone and chat stay inside the native editor.
use std::sync::{Arc, Mutex};

#[derive(Default)]
pub struct AssistantPanel {
    pub open: bool,
    pub immersive: bool,
    web: Option<wry::WebView>,
    messages: Arc<Mutex<Vec<String>>>,
    last_context: String,
    last_token: String,
    error: Option<String>,
    pub pointer: serde_json::Value,
    pub targets: Vec<serde_json::Value>,
    pub focus: Option<serde_json::Value>,
    pub pick: bool,
    pub drag: Option<eframe::egui::Pos2>,
    pub selection: Option<serde_json::Value>,
    pub viewport: serde_json::Value,
    pub production: Vec<serde_json::Value>,
    pub production_label: Option<String>,
    pub production_at: Option<std::time::Instant>,
}

impl AssistantPanel {
    pub fn new() -> Self { Self { open: false, immersive: true, ..Default::default() } }
    pub fn show(&mut self, ctx: &eframe::egui::Context, frame: &eframe::Frame,
                context: serde_json::Value, token: &str) -> Vec<String> {
        if !self.open {
            self.web = None;
            self.last_context.clear();
            self.last_token.clear();
            return Vec::new();
        }
        let rect = if self.immersive { ctx.screen_rect() } else { eframe::egui::SidePanel::right("editor_conversation")
            .resizable(true).default_width(355.0).width_range(300.0..=520.0)
            .show(ctx, |ui| {
                ui.label("ダンに接続しています…");
                if let Some(error) = &self.error { ui.label(error); }
                ui.available_rect_before_wrap()
            }).response.rect };
        let bounds = wry::Rect {
            position: wry::dpi::LogicalPosition::new(rect.left() as f64, rect.top() as f64).into(),
            size: wry::dpi::LogicalSize::new(rect.width() as f64, rect.height() as f64).into(),
        };
        if self.web.is_none() && self.error.is_none() {
            let messages = self.messages.clone();
            let repaint = ctx.clone();
            let bootstrap = serde_json::json!({"token": token}).to_string();
            let auto_voice = self.immersive;
            let initial = format!("window.__editorBootstrap={bootstrap};window.__autoStartVoice={auto_voice};");
            match wry::WebViewBuilder::new()
                .with_url("http://127.0.0.1:8000/api/v1/editor-assistant/page")
                .with_bounds(bounds.clone())
                .with_initialization_script(&initial)
                .with_navigation_handler(|url| url == "about:blank" || url.starts_with("https://www.youtube-nocookie.com/embed/") || url.starts_with("https://player.vimeo.com/video/") || url.trim_end_matches('/') == "http://127.0.0.1:8000/api/v1/editor-assistant/page")
                .with_ipc_handler(move |request| {
                    if let Ok(mut messages) = messages.lock() { messages.push(request.body().clone()); }
                    repaint.request_repaint();
                })
                .build_as_child(frame) {
                Ok(web) => self.web = Some(web),
                Err(e) => self.error = Some(format!("会話パネルを開けませんでした: {e}")),
            }
        }
        let messages: Vec<String> = self.messages.lock().map(|mut m| m.drain(..).collect()).unwrap_or_default();
        let refreshed = if messages.iter().any(|m| m == "auth") {
            crate::refresh_api_token_from_file();
            crate::API_TOKEN.read().unwrap().clone()
        } else { None };
        let token = refreshed.as_deref().unwrap_or(token);
        if messages.iter().any(|m| m == "ready" || m == "auth") {
            self.last_context.clear(); self.last_token.clear();
        }
        if let Some(web) = &self.web {
            match messages.iter().rev().find(|m| m.as_str() == "return_keyboard").map(|m| m.as_str()) {
                Some("return_keyboard") => { let _ = web.focus_parent(); },
                _ => {},
            }
            let _ = web.set_bounds(bounds);
            let _ = web.evaluate_script(&format!("window.__setStageMode?.({});",self.immersive));
            if self.last_token != token || messages.iter().any(|m| m == "ready" || m == "auth") {
                let auth = serde_json::json!({"token": token});
                let _ = web.evaluate_script(&format!("window.__editorBootstrap={auth};window.__setEditorAuth?.({auth});"));
                self.last_token = token.to_string();
            }
            let value = context.to_string();
            if value != self.last_context {
                let _ = web.evaluate_script(&format!("window.__updateEditorContext?.({value});"));
                self.last_context = value;
            }
        }
        messages
    }

    pub fn reply(&self, id: &str, result: serde_json::Value) {
        if let Some(web) = &self.web {
            let id = serde_json::json!(id);
            let _ = web.evaluate_script(&format!("window.__editorAck?.({id},{result});"));
        }
    }
}
