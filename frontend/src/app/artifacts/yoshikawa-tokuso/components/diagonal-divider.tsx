import { cn } from "@/lib/utils";

type DiagonalDividerProps = {
  color?: string;
  direction?: "tl-br" | "tr-bl";
  className?: string;
};

/**
 * 新明和HP風の斜めスラッシュ装飾（"/"）。
 * 見出しやセクションの目印に使う。
 */
export function DiagonalDivider({
  color = "var(--yk-gold)",
  direction = "tl-br",
  className,
}: DiagonalDividerProps) {
  return (
    <span
      className={cn(
        "inline-block h-6 w-1.5 rounded-sm shrink-0",
        className,
      )}
      style={{
        backgroundColor: color,
        transform: direction === "tl-br" ? "skewX(-18deg)" : "skewX(18deg)",
      }}
      aria-hidden
    />
  );
}
