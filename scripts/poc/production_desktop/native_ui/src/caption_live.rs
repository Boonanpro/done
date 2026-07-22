use std::collections::HashSet;
use std::sync::{Mutex, OnceLock};

/// Captions temporarily owned by the WebView while the GPU cache catches up.
///
/// This deliberately holds no caption text. `clip.text` in the document is the
/// sole source of truth for editing, timeline labels, preview payloads and saves.
fn live_ids() -> &'static Mutex<HashSet<String>> {
    static LIVE: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();
    LIVE.get_or_init(|| Mutex::new(HashSet::new()))
}

pub fn activate(clip_id: &str) {
    if let Ok(mut live) = live_ids().lock() {
        live.insert(clip_id.to_string());
    }
}

pub fn clear(clip_id: &str) {
    if let Ok(mut live) = live_ids().lock() {
        live.remove(clip_id);
    }
}

pub fn is_active(clip_id: &str) -> bool {
    live_ids()
        .lock()
        .ok()
        .map(|live| live.contains(clip_id))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ownership_is_memory_only_and_clearable() {
        activate("cap-1");
        assert!(is_active("cap-1"));
        clear("cap-1");
        assert!(!is_active("cap-1"));
    }
}
