//! Timeline-aware presentation ring.
//!
//! The old preview queue was hard-wired to `Vec<u8>` RGBA frames, which forced every
//! completed compositor frame through CPU memory before it could be presented.  This
//! type deliberately owns only ordering and timeline semantics; the payload is generic
//! so the same proven ring policy can carry a D3D texture in the native presenter.

use std::collections::VecDeque;

#[derive(Debug)]
pub struct FrameRing<T> {
    frames: VecDeque<(f64, f64, T)>, // (timeline t, effective t, payload)
}

impl<T> Default for FrameRing<T> {
    fn default() -> Self {
        Self { frames: VecDeque::new() }
    }
}

impl<T> FrameRing<T> {
    pub fn clear(&mut self) { self.frames.clear(); }
    pub fn len(&self) -> usize { self.frames.len() }
    pub fn is_empty(&self) -> bool { self.frames.is_empty() }
    pub fn front_t(&self) -> Option<f64> { self.frames.front().map(|f| f.0) }
    pub fn back_t(&self) -> Option<f64> { self.frames.back().map(|f| f.0) }

    /// Push monotonic frames. A seek/cut invalidates the caller's ring first, so an
    /// out-of-order value is a programmer error and must not silently poison display.
    pub fn push(&mut self, t: f64, effective_t: f64, payload: T) {
        debug_assert!(self.frames.back().map(|f| f.0 < t + 1e-9).unwrap_or(true));
        self.frames.push_back((t, effective_t, payload));
    }

    /// Discard frames that can no longer be shown, then return the newest frame that
    /// belongs at `clock_t`. Ownership transfers directly to the presentation surface;
    /// no pixel clone is involved.
    pub fn take_for_clock(&mut self, clock_t: f64, frame_step: f64) -> Option<(f64, f64, T)> {
        while self.frames.front().map(|f| f.0 < clock_t - frame_step).unwrap_or(false) {
            self.frames.pop_front();
        }
        let mut chosen = None;
        while self.frames.front().map(|f| f.0 <= clock_t).unwrap_or(false) {
            chosen = self.frames.pop_front();
        }
        chosen
    }
}

#[cfg(test)]
mod tests {
    use super::FrameRing;

    #[test]
    fn presents_latest_frame_at_clock_without_copying_payload() {
        let mut r = FrameRing::default();
        r.push(1.0, 1.0, String::from("a"));
        r.push(1.033, 1.033, String::from("b"));
        r.push(1.066, 1.066, String::from("c"));
        assert_eq!(r.take_for_clock(1.05, 1.0 / 30.0), Some((1.033, 1.033, String::from("b"))));
        assert_eq!(r.take_for_clock(1.07, 1.0 / 30.0), Some((1.066, 1.066, String::from("c"))));
    }
}
