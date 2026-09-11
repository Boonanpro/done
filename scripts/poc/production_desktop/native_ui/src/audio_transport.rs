//! Device failure must not take away the editor's play/pause/seek clock.
use std::time::{Duration, Instant};
use anyhow::Result;

pub trait Output {
    fn open() -> Result<Self> where Self: Sized;
    fn start(&mut self, t: f64, speed: f64) -> Result<()>;
    fn stop(&mut self);
    fn clock(&self) -> f64;
    fn fill(&mut self, doc: &crate::model::Doc, speed: f64) -> Result<()>;
    fn underruns(&self) -> u64;
}

impl Output for crate::media::AudioOut {
    fn open() -> Result<Self> { Self::new() }
    fn start(&mut self, t: f64, speed: f64) -> Result<()> { self.start_at(t, speed) }
    fn stop(&mut self) { self.stop() }
    fn clock(&self) -> f64 { self.clock() }
    fn fill(&mut self, doc: &crate::model::Doc, speed: f64) -> Result<()> { self.fill(doc, speed) }
    fn underruns(&self) -> u64 { self.underruns }
}

pub struct Transport<D: Output> {
    device: Option<D>,
    base: f64,
    since: Instant,
    speed: f64,
    playing: bool,
    retry_at: Instant,
    pub underruns: u64,
}

impl<D: Output> Transport<D> {
    pub fn new() -> Self {
        Self { device: D::open().ok(), base: 0.0, since: Instant::now(),
            speed: 1.0, playing: false, retry_at: Instant::now(), underruns: 0 }
    }
    pub fn unavailable(&self) -> bool { self.device.is_none() }
    pub fn start_at(&mut self, t: f64, speed: f64) -> Result<()> {
        self.base = t; self.since = Instant::now(); self.speed = speed; self.playing = true;
        if let Some(d) = self.device.as_mut() {
            if let Err(e) = d.start(t, speed) { self.lose_device(t); return Err(e); }
        }
        Ok(())
    }
    fn lose_device(&mut self, t: f64) {
        if let Some(mut d) = self.device.take() { d.stop(); }
        self.base = t; self.since = Instant::now();
        self.retry_at = Instant::now() + Duration::from_millis(250);
    }
    pub fn stop(&mut self) {
        self.base = self.clock(); self.playing = false;
        if let Some(d) = self.device.as_mut() { d.stop(); }
    }
    pub fn clock(&self) -> f64 {
        if !self.playing { return self.base; }
        self.device.as_ref().map(|d| d.clock())
            .unwrap_or_else(|| self.base + self.since.elapsed().as_secs_f64() * self.speed)
    }
    fn reconnect(&mut self) {
        if self.device.is_some() || Instant::now() < self.retry_at { return; }
        self.retry_at = Instant::now() + Duration::from_secs(1);
        let t = self.clock();
        if let Ok(mut d) = D::open() {
            if d.start(t, self.speed).is_ok() {
                self.device = Some(d);
                eprintln!("AUDIO_RECONNECTED t={t:.3}");
            }
        }
    }
    pub fn fill(&mut self, doc: &crate::model::Doc, speed: f64) -> Result<()> {
        self.reconnect();
        // Remember the last good clock before calling into an invalidated endpoint.
        let t = self.clock();
        if let Some(d) = self.device.as_mut() {
            if let Err(e) = d.fill(doc, speed) { self.lose_device(t); return Err(e); }
            self.underruns = d.underruns();
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Device(f64);
    impl Output for Device {
        fn open() -> Result<Self> { Ok(Self(0.0)) }
        fn start(&mut self, t:f64, _:f64) -> Result<()> { self.0=t; Ok(()) }
        fn stop(&mut self) {}
        fn clock(&self) -> f64 { self.0 }
        fn fill(&mut self, _: &crate::model::Doc, _:f64) -> Result<()> { anyhow::bail!("0x88890004") }
        fn underruns(&self) -> u64 { 0 }
    }
    #[test]
    fn device_loss_keeps_transport_controllable_and_reconnects_at_current_time() {
        let mut t=Transport::<Device>::new();
        t.start_at(12.0,2.0).unwrap();t.lose_device(12.0);
        t.since=Instant::now()-Duration::from_millis(100);
        assert!(t.clock()>=12.2);
        t.stop();let stopped=t.clock();t.since-=Duration::from_secs(1);
        assert_eq!(t.clock(),stopped);
        t.start_at(40.0,1.0).unwrap();
        t.since=Instant::now()-Duration::from_millis(200);
        t.retry_at=Instant::now();t.reconnect();
        assert!(!t.unavailable());assert!((40.2..40.3).contains(&t.clock()));
    }
    #[test]
    fn invalidated_device_is_discarded_on_fill_error() {
        let doc=crate::model::Doc::from_raw(serde_json::json!([]),"","").unwrap();
        let mut t=Transport::<Device>::new();t.start_at(195.87,1.0).unwrap();
        assert!(t.fill(&doc,1.0).is_err());assert!(t.unavailable());
        t.since=Instant::now()-Duration::from_millis(200);
        assert!(t.clock()>196.0);
        t.stop();assert!(!t.playing);
        t.start_at(30.0,1.0).unwrap();assert!((30.0..30.1).contains(&t.clock()));
    }
}
