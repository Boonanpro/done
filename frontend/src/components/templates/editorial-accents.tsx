import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

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
