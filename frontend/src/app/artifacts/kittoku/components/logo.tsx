import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/utils";

type LogoProps = {
  size?: "sm" | "md" | "lg";
  showText?: boolean;
  variant?: "light" | "dark";
  className?: string;
  href?: string;
};

const SIZE_MAP = {
  sm: { img: 32, text: "text-sm" },
  md: { img: 40, text: "text-base" },
  lg: { img: 56, text: "text-lg" },
};

export function Logo({
  size = "md",
  showText = true,
  variant = "light",
  className,
  href = "/artifacts/kittoku",
}: LogoProps) {
  const s = SIZE_MAP[size];
  const content = (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Image
        src="/kikkawa/logo.png"
        alt="吉川特装（きっかわとくそう）"
        width={s.img}
        height={s.img}
        className="shrink-0 object-contain"
        priority
      />
      {showText && (
        <span className="flex flex-col leading-tight">
          <span
            className={cn(
              "font-headline font-black",
              s.text,
              variant === "light" ? "text-[var(--yk-navy)]" : "text-white",
            )}
          >
            吉川特装
          </span>
          <span
            className={cn(
              "font-eyebrow text-[10px]",
              variant === "light" ? "text-[var(--yk-steel)]" : "text-white/70",
            )}
          >
            KIKKAWA TOKUSOU
          </span>
        </span>
      )}
    </span>
  );
  if (href) {
    return <Link href={href}>{content}</Link>;
  }
  return content;
}
