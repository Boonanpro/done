import { Award } from "lucide-react";
import { cn } from "@/lib/utils";

type CertifiedBadgeProps = {
  variant?: "light" | "dark";
  size?: "sm" | "md" | "lg";
  className?: string;
};

export function CertifiedBadge({
  variant = "dark",
  size = "md",
  className,
}: CertifiedBadgeProps) {
  const sizeMap = {
    sm: "px-2.5 py-1 text-[10px] gap-1.5",
    md: "px-3.5 py-1.5 text-xs gap-2",
    lg: "px-5 py-2.5 text-sm gap-2.5",
  };
  const iconSize = { sm: "h-3 w-3", md: "h-3.5 w-3.5", lg: "h-4 w-4" }[size];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border font-bold tracking-wider",
        variant === "dark"
          ? "bg-[var(--yk-navy)] text-white border-[var(--yk-gold)]"
          : "bg-white text-[var(--yk-navy)] border-[var(--yk-navy)]",
        sizeMap[size],
        className,
      )}
    >
      <Award className={cn(iconSize, "text-[var(--yk-gold)] fill-[var(--yk-gold)]/30")} />
      <span className="font-headline">主要メーカー指定工場</span>
    </span>
  );
}
