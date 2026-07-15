use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

fn texts() -> &'static Mutex<HashMap<String, String>> {
    static LIVE: OnceLock<Mutex<HashMap<String, String>>> = OnceLock::new();
    LIVE.get_or_init(|| Mutex::new(HashMap::new()))
}

pub fn set(clip_id: &str, text: String) {
    if let Ok(mut live) = texts().lock() {
        live.insert(clip_id.to_string(), text);
    }
}

pub fn clear(clip_id: &str) {
    if let Ok(mut live) = texts().lock() {
        live.remove(clip_id);
    }
}

pub fn get(clip_id: &str) -> Option<String> {
    texts().lock().ok()?.get(clip_id).cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn editing_text_is_memory_only_and_clearable() {
        set("cap-1", "入力中".to_string());
        assert_eq!(get("cap-1").as_deref(), Some("入力中"));
        clear("cap-1");
        assert!(get("cap-1").is_none());
    }
}
