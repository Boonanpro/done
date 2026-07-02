//! `danpv://` source — plays a pop-out bake (`{key}.pv.mp4`, ONE mp4 with TWO H.264 video
//! tracks: v:0 = color, v:1 = matte-as-luma) as a single ALPHA video stream, so GES composites
//! a pop-out like any ordinary clip. This replaces the old ProRes 4444 `.mov` (200+ Mbps,
//! CPU-only `avdec_prores`) that made the whole timeline heavy whenever the playhead touched
//! a pop-out clip; the two H.264 tracks decode in a few ms/frame.
//!
//! Internals: filesrc → qtdemux → (queue → h264parse → avdec_h264 → videoconvert → I420) ×2
//! → alphacombine (color on `sink`, matte on `alpha`) → videoconvert → ghost `src` (A420/AYUV,
//! negotiated by downstream). ONE demuxer means a seek arriving from nle/GES through either
//! branch reseeks BOTH tracks in lockstep — this is why the bake is a single two-track file
//! rather than two files. Registered as a URI handler so `GESUriClip` / GstDiscoverer /
//! uridecodebin treat it exactly like a normal media file.

use gstreamer as gst;
use gst::glib;
use gst::prelude::*;

mod imp {
    use super::*;
    use gst::subclass::prelude::*;
    use std::sync::Mutex;
    use std::sync::OnceLock;

    #[derive(Default)]
    pub struct DanPvSrc {
        pub(super) uri: Mutex<Option<String>>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for DanPvSrc {
        const NAME: &'static str = "DanPvSrc";
        type Type = super::DanPvSrc;
        type ParentType = gst::Bin;
        type Interfaces = (gst::URIHandler,);
    }

    impl ObjectImpl for DanPvSrc {
        fn constructed(&self) {
            self.parent_constructed();
            let obj = self.obj();

            let make = |factory: &str, name: &str| {
                gst::ElementFactory::make(factory)
                    .name(name)
                    .build()
                    .unwrap_or_else(|_| panic!("danpvsrc: missing element {factory}"))
            };
            let i420 = |name: &str| {
                let c = make("capsfilter", name);
                c.set_property(
                    "caps",
                    gst::Caps::builder("video/x-raw").field("format", "I420").build(),
                );
                c
            };

            let filesrc = make("filesrc", "pv_filesrc");
            let demux = make("qtdemux", "pv_demux");
            // per-branch queues: a demuxer with two consumers deadlocks without them
            let q_c = make("queue", "pv_q_c");
            let parse_c = make("h264parse", "pv_parse_c");
            let dec_c = make("avdec_h264", "pv_dec_c");
            let conv_c = make("videoconvert", "pv_conv_c");
            let caps_c = i420("pv_caps_c");
            let q_a = make("queue", "pv_q_a");
            let parse_a = make("h264parse", "pv_parse_a");
            let dec_a = make("avdec_h264", "pv_dec_a");
            let conv_a = make("videoconvert", "pv_conv_a");
            let caps_a = i420("pv_caps_a");
            let combine = make("alphacombine", "pv_combine");
            let out_conv = make("videoconvert", "pv_out_conv");

            obj.add_many([
                &filesrc, &demux, &q_c, &parse_c, &dec_c, &conv_c, &caps_c, &q_a, &parse_a,
                &dec_a, &conv_a, &caps_a, &combine, &out_conv,
            ])
            .expect("danpvsrc: add children");
            filesrc.link(&demux).expect("danpvsrc: filesrc→demux");
            gst::Element::link_many([&q_c, &parse_c, &dec_c, &conv_c, &caps_c])
                .expect("danpvsrc: color chain");
            gst::Element::link_many([&q_a, &parse_a, &dec_a, &conv_a, &caps_a])
                .expect("danpvsrc: alpha chain");
            caps_c
                .link_pads(Some("src"), &combine, Some("sink"))
                .expect("danpvsrc: color→combine");
            caps_a
                .link_pads(Some("src"), &combine, Some("alpha"))
                .expect("danpvsrc: matte→combine.alpha");
            combine.link(&out_conv).expect("danpvsrc: combine→out");

            // qtdemux pads appear during preroll: video_0 = color, video_1 = matte (mux order
            // fixed by the bake's ffmpeg -map order)
            let q_c_weak = q_c.downgrade();
            let q_a_weak = q_a.downgrade();
            demux.connect_pad_added(move |_demux, pad| {
                let name = pad.name();
                let target = if name == "video_0" {
                    q_c_weak.upgrade()
                } else if name == "video_1" {
                    q_a_weak.upgrade()
                } else {
                    None
                };
                if let Some(t) = target {
                    if let Some(sink) = t.static_pad("sink") {
                        if !sink.is_linked() {
                            let _ = pad.link(&sink);
                        }
                    }
                }
            });

            let src = out_conv.static_pad("src").expect("danpvsrc: out src pad");
            let ghost = gst::GhostPad::builder_with_target(&src)
                .expect("danpvsrc: ghost target")
                .name("src")
                .build();
            obj.add_pad(&ghost).expect("danpvsrc: add ghost pad");
        }
    }

    impl GstObjectImpl for DanPvSrc {}
    impl BinImpl for DanPvSrc {}

    impl ElementImpl for DanPvSrc {
        fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
            static META: OnceLock<gst::subclass::ElementMetadata> = OnceLock::new();
            Some(META.get_or_init(|| {
                gst::subclass::ElementMetadata::new(
                    "Dan pop-out two-track source",
                    "Source/Video",
                    "Plays a two-track (color+alpha-luma) mp4 as one alpha video stream",
                    "dan",
                )
            }))
        }

        fn pad_templates() -> &'static [gst::PadTemplate] {
            static TEMPLATES: OnceLock<Vec<gst::PadTemplate>> = OnceLock::new();
            TEMPLATES.get_or_init(|| {
                let src = gst::PadTemplate::new(
                    "src",
                    gst::PadDirection::Src,
                    gst::PadPresence::Always,
                    &gst::Caps::new_any(),
                )
                .expect("danpvsrc: src template");
                vec![src]
            })
        }
    }

    impl URIHandlerImpl for DanPvSrc {
        const URI_TYPE: gst::URIType = gst::URIType::Src;

        fn protocols() -> &'static [&'static str] {
            &["danpv"]
        }

        fn uri(&self) -> Option<String> {
            self.uri.lock().unwrap().clone()
        }

        fn set_uri(&self, uri: &str) -> Result<(), glib::Error> {
            // danpv:///D:/path/to/key.pv.mp4 (percent-encoded like file://)
            let rest = uri.strip_prefix("danpv://").ok_or_else(|| {
                glib::Error::new(gst::URIError::BadUri, "expected danpv:// URI")
            })?;
            let raw = rest.strip_prefix('/').unwrap_or(rest); // "/D:/…" → "D:/…"
            let path = glib::uri_unescape_string(raw, None::<&str>)
                .map(|s| s.to_string())
                .unwrap_or_else(|| raw.to_string());
            let obj = self.obj();
            let filesrc = obj
                .by_name("pv_filesrc")
                .ok_or_else(|| glib::Error::new(gst::URIError::BadState, "no filesrc"))?;
            filesrc.set_property("location", &path);
            *self.uri.lock().unwrap() = Some(uri.to_string());
            Ok(())
        }
    }
}

glib::wrapper! {
    pub struct DanPvSrc(ObjectSubclass<imp::DanPvSrc>)
        @extends gst::Bin, gst::Element, gst::Object,
        @implements gst::URIHandler;
}

/// Register the element (idempotent per process). PRIMARY rank so uridecodebin resolves the
/// `danpv` protocol to this element.
pub fn register() -> Result<(), glib::BoolError> {
    gst::Element::register(
        None,
        "danpvsrc",
        gst::Rank::PRIMARY,
        DanPvSrc::static_type(),
    )
}
