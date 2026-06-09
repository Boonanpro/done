import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type SvgAccentProps = {
  className?: string;
  strokeWidth?: number;
};

type RoundelBadgeProps = {
  eyebrow?: ReactNode;
  value: ReactNode;
  caption?: ReactNode;
  className?: string;
};

export function RoundelBadge({ eyebrow, value, caption, className }: RoundelBadgeProps) {
  return (
    <div
      className={cn(
        "flex aspect-square w-32 flex-col items-center justify-center rounded-full border border-current p-4 text-center text-current sm:w-40",
        className,
      )}
    >
      {eyebrow && <div className="text-[11px] leading-none tracking-[0.08em] opacity-80">{eyebrow}</div>}
      <div className="mt-2 font-headline text-2xl leading-none sm:text-3xl">{value}</div>
      {caption && <div className="mt-2 text-[10px] leading-relaxed opacity-75">{caption}</div>}
    </div>
  );
}

type SealMarkProps = {
  children: ReactNode;
  className?: string;
};

export function SealMark({ children, className }: SealMarkProps) {
  return (
    <span
      className={cn(
        "inline-flex aspect-square min-w-9 items-center justify-center border border-current p-1 font-headline text-xs leading-none tracking-[0.08em] text-current",
        className,
      )}
    >
      {children}
    </span>
  );
}

type RuleDividerProps = {
  label?: ReactNode;
  className?: string;
};

export function RuleDivider({ label, className }: RuleDividerProps) {
  return (
    <div className={cn("flex items-center gap-4 text-muted-foreground", className)}>
      <span className="h-px flex-1 bg-current/30" />
      {label && <span className="font-label text-[10px] uppercase tracking-[0.18em]">{label}</span>}
      <span className="h-px flex-1 bg-current/30" />
    </div>
  );
}

export function BrushStroke({ className, strokeWidth = 2.2 }: SvgAccentProps) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 180 36"
      fill="none"
      className={cn("h-7 w-36 text-current", className)}
      preserveAspectRatio="none"
    >
      <path
        d="M3 23C25 8 47 8 68 19C86 28 101 30 119 21C137 12 153 10 177 16"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.78"
      />
      <path
        d="M18 19C33 13 49 13 63 21C77 29 93 31 111 24"
        stroke="currentColor"
        strokeWidth={Math.max(1, strokeWidth * 0.45)}
        strokeLinecap="round"
        opacity="0.38"
      />
    </svg>
  );
}

export function InkCircle({ className, strokeWidth = 2 }: SvgAccentProps) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 120 120"
      fill="none"
      className={cn("aspect-square w-28 text-current", className)}
    >
      <path
        d="M62 8C86 9 108 25 113 51C119 82 95 108 65 113C36 118 10 100 7 68C4 37 27 9 62 8Z"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.82"
      />
      <path
        d="M26 22C12 36 8 58 15 77"
        stroke="currentColor"
        strokeWidth={Math.max(1, strokeWidth * 0.7)}
        strokeLinecap="round"
        opacity="0.34"
      />
    </svg>
  );
}

export function HandRule({ className, strokeWidth = 1.5 }: SvgAccentProps) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 240 18"
      fill="none"
      className={cn("h-4 w-full text-current", className)}
      preserveAspectRatio="none"
    >
      <path
        d="M2 9C34 7 65 10 96 8.5C132 6.8 166 9.5 202 8C215 7.5 227 7.8 238 9"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        opacity="0.6"
      />
      <path
        d="M15 12C56 10 87 13 129 11.5C163 10.3 193 12 225 11"
        stroke="currentColor"
        strokeWidth={Math.max(1, strokeWidth * 0.55)}
        strokeLinecap="round"
        opacity="0.28"
      />
    </svg>
  );
}

type PhotoCaptionProps = {
  children: ReactNode;
  className?: string;
};

export function PhotoCaption({ children, className }: PhotoCaptionProps) {
  return (
    <p className={cn("mt-3 text-xs leading-relaxed text-muted-foreground", className)}>
      {children}
    </p>
  );
}

type InfoStripItem = {
  label: ReactNode;
  value: ReactNode;
};

type InfoStripProps = {
  items: InfoStripItem[];
  className?: string;
};

export function InfoStrip({ items, className }: InfoStripProps) {
  return (
    <dl
      className={cn(
        "grid divide-y divide-border border-y border-border md:grid-cols-3 md:divide-x md:divide-y-0",
        className,
      )}
    >
      {items.map((item, index) => (
        <div key={index} className="px-5 py-5 md:px-7">
          <dt className="font-label text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-2 font-headline text-xl leading-tight text-foreground">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

type EditorialFrameProps = {
  children: ReactNode;
  className?: string;
  inset?: boolean;
};

export function EditorialFrame({ children, className, inset = true }: EditorialFrameProps) {
  return (
    <div
      className={cn(
        "relative border border-border bg-card/30",
        inset && "p-3 sm:p-4",
        className,
      )}
    >
      <span className="absolute -left-px -top-px h-4 w-4 border-l border-t border-primary" />
      <span className="absolute -right-px -bottom-px h-4 w-4 border-b border-r border-primary" />
      {children}
    </div>
  );
}
