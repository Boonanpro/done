"use client";

import * as React from "react";
import { Play, Pause } from "lucide-react";

type Props = {
  src: string;
  poster?: string;
  alt?: string;
};

export function ServiceVideoCard({ src, poster, alt }: Props) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = React.useState(true);

  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, []);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().catch(() => {
        /* ignore */
      });
    } else {
      v.pause();
    }
  };

  return (
    <div className="relative aspect-[16/9] bg-[var(--yk-navy)]/5 overflow-hidden">
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        autoPlay
        loop
        muted
        playsInline
        preload="metadata"
        className="absolute inset-0 w-full h-full object-cover"
        aria-label={alt}
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "動画を停止" : "動画を再生"}
        className="absolute bottom-3 right-3 h-9 w-9 rounded-full bg-white/85 hover:bg-white text-[var(--yk-navy)] flex items-center justify-center shadow-md transition-colors backdrop-blur-sm"
      >
        {playing ? (
          <Pause className="h-4 w-4" fill="currentColor" />
        ) : (
          <Play className="h-4 w-4 ml-0.5" fill="currentColor" />
        )}
      </button>
    </div>
  );
}
