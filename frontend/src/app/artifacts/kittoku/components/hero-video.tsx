"use client";

import * as React from "react";
import { Play } from "lucide-react";

type Props = {
  src: string;
  poster: string;
};

export function HeroVideo({ src, poster }: Props) {
  const ref = React.useRef<HTMLVideoElement>(null);
  const [needsTap, setNeedsTap] = React.useState(false);

  React.useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const tryPlay = () => {
      const p = v.play();
      if (p && typeof p.catch === "function") {
        p.catch(() => {
          setNeedsTap(true);
        });
      }
    };
    if (v.readyState >= 2) {
      tryPlay();
    } else {
      v.addEventListener("loadeddata", tryPlay, { once: true });
    }
  }, []);

  const onUserPlay = () => {
    const v = ref.current;
    if (!v) return;
    v.play()
      .then(() => setNeedsTap(false))
      .catch(() => {
        /* ignore */
      });
  };

  return (
    <>
      <video
        ref={ref}
        className="absolute inset-0 w-full h-full object-cover"
        style={{ filter: "brightness(0.5) saturate(1.05)" }}
        src={src}
        poster={poster}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        aria-label="吉川特装 紹介動画"
      />
      {needsTap && (
        <button
          type="button"
          onClick={onUserPlay}
          className="absolute inset-0 flex items-center justify-center bg-black/20 hover:bg-black/30 transition-colors"
          aria-label="動画を再生"
        >
          <span className="h-16 w-16 rounded-full bg-white/90 text-[var(--yk-navy)] flex items-center justify-center shadow-lg">
            <Play className="h-7 w-7 ml-1" fill="currentColor" />
          </span>
        </button>
      )}
    </>
  );
}
