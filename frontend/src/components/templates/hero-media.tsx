import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * HeroMedia — ヒーロー画像 / 動画 + テキストコンテンツの正しい重ね方を強制するコンポーネント。
 *
 * 重要な設計目的:
 *   ヒーローセクションでよくある「<img>/<video> の上に半透明 div を重ねる」パターンを
 *   そもそも書かせない。 暗転 / ぼかし / 方向性フェードは props として宣言し、
 *   内部で CSS filter / mask-image に変換して **メディア自体に当てる**。
 *   結果として、ユーザーが inspector でクリックすれば必ず <img>/<video> が直接選択される。
 *
 * 使用例:
 *   <HeroMedia kind="video" src="/hero.mp4" darken={50} blur={1} fade="left">
 *     <div className="mx-auto max-w-7xl px-6 py-32">
 *       <h1>働く車を、もっと賢く</h1>
 *     </div>
 *   </HeroMedia>
 */

type Fade = "none" | "left" | "right" | "top" | "bottom";

type CommonProps = {
  /** 暗転の強さ 0-100 (%) — 内部で brightness CSS filter に変換 */
  darken?: number;
  /** ぼかし 0-20 (px) — 内部で blur CSS filter に変換 */
  blur?: number;
  /** 方向性フェード — 内部で mask-image に変換 (overlay div を作らない) */
  fade?: Fade;
  /** テキスト等のコンテンツ。メディアの上にレイヤーされる */
  children?: React.ReactNode;
  /** ヒーローセクション全体の className */
  className?: string;
  /** メディアエリアの最小高 (例: "min-h-[80vh]") */
  minHeightClass?: string;
  /** メディア(<img>/<video>)に付ける data-edit-id — inspector で差し替え対象にする */
  mediaEditId?: string;
};

type ImageProps = CommonProps & {
  kind: "image";
  src: string;
  alt: string;
};

type VideoProps = CommonProps & {
  kind: "video";
  src: string;
  poster?: string;
  /** 動画の再生制御 (デフォルト: autoplay loop muted) */
  autoPlay?: boolean;
  loop?: boolean;
  muted?: boolean;
};

type HeroMediaProps = ImageProps | VideoProps;

function buildFilter(darken?: number, blur?: number): string | undefined {
  const parts: string[] = [];
  if (darken && darken > 0) {
    parts.push(`brightness(${((100 - darken) / 100).toFixed(2)})`);
  }
  if (blur && blur > 0) {
    parts.push(`blur(${blur}px)`);
  }
  return parts.length > 0 ? parts.join(" ") : undefined;
}

function buildMask(fade?: Fade): string | undefined {
  if (!fade || fade === "none") return undefined;
  const direction =
    fade === "left"
      ? "to right"
      : fade === "right"
        ? "to left"
        : fade === "top"
          ? "to bottom"
          : "to top";
  // fade 方向のテキスト側を黒く保ち、写真側を透明にしていく
  return `linear-gradient(${direction}, black 0%, black 60%, transparent 100%)`;
}

export function HeroMedia(props: HeroMediaProps) {
  const {
    darken,
    blur,
    fade,
    children,
    className,
    minHeightClass = "min-h-[60vh]",
    mediaEditId,
  } = props;
  const filter = buildFilter(darken, blur);
  const maskImage = buildMask(fade);
  const mediaStyle: React.CSSProperties = {
    filter,
    maskImage,
    WebkitMaskImage: maskImage,
  };

  return (
    <section
      className={cn("relative overflow-hidden", minHeightClass, className)}
    >
      {props.kind === "image" ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          data-edit-id={mediaEditId}
          src={props.src}
          alt={props.alt}
          className="absolute inset-0 h-full w-full object-cover"
          style={mediaStyle}
        />
      ) : (
        <video
          data-edit-id={mediaEditId}
          src={props.src}
          poster={props.poster}
          autoPlay={props.autoPlay ?? true}
          loop={props.loop ?? true}
          muted={props.muted ?? true}
          playsInline
          preload="metadata"
          className="absolute inset-0 h-full w-full object-cover"
          style={mediaStyle}
        />
      )}
      {children && <div className="relative">{children}</div>}
    </section>
  );
}
