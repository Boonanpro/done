import { createElement } from "react";
import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

import { cn } from "@/lib/utils";

type TextProps = {
  as?: ElementType;
  children: ReactNode;
  className?: string;
};

type TextNativeProps = Omit<ComponentPropsWithoutRef<"div">, keyof TextProps>;

const jpFeatureStyle = {
  fontFeatureSettings: '"palt" 1',
} as const;

function renderElement(
  as: ElementType | undefined,
  fallback: ElementType,
  props: Record<string, unknown>,
  children: ReactNode,
) {
  return createElement(as ?? fallback, props, children);
}

export function SectionKicker({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "div",
    {
      className: cn(
        "font-label text-[11px] uppercase tracking-[0.18em] text-muted-foreground",
        className,
      ),
      ...props,
    },
    children,
  );
}

export function SectionTitle({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "h2",
    {
      className: cn(
        "font-headline text-[clamp(2rem,4vw,4.75rem)] font-medium leading-[1.16] tracking-normal text-foreground",
        className,
      ),
      style: jpFeatureStyle,
      ...props,
    },
    children,
  );
}

export function HeroCopy({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "h1",
    {
      className: cn(
        "font-headline text-[clamp(2.8rem,7vw,7.75rem)] font-medium leading-[1.05] tracking-normal text-foreground",
        className,
      ),
      style: jpFeatureStyle,
      ...props,
    },
    children,
  );
}

export function VerticalHeroCopy({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "h1",
    {
      className: cn(
        "font-headline text-[clamp(2.5rem,6vw,6.5rem)] font-medium leading-[1.22] tracking-[0.06em] text-foreground",
        className,
      ),
      style: { ...jpFeatureStyle, writingMode: "vertical-rl" },
      ...props,
    },
    children,
  );
}

export function LeadCopy({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "p",
    {
      className: cn(
        "max-w-2xl text-[clamp(1.05rem,1.7vw,1.45rem)] leading-[1.95] text-foreground",
        className,
      ),
      style: jpFeatureStyle,
      ...props,
    },
    children,
  );
}

export function BodyCopy({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "p",
    {
      className: cn("max-w-prose text-[15px] leading-[1.95] text-muted-foreground", className),
      style: jpFeatureStyle,
      ...props,
    },
    children,
  );
}

export function MetaLabel({
  as,
  children,
  className,
  ...props
}: TextProps & TextNativeProps) {
  return renderElement(
    as,
    "span",
    {
      className: cn(
        "font-label text-[11px] uppercase leading-none tracking-[0.16em] text-muted-foreground",
        className,
      ),
      ...props,
    },
    children,
  );
}

type EditorialButtonProps = TextProps &
  TextNativeProps & {
    variant?: "outline" | "solid" | "ghost";
    href?: string;
    target?: string;
    rel?: string;
    type?: "button" | "submit" | "reset";
  };

export function EditorialButton({
  as,
  children,
  className,
  variant = "outline",
  ...props
}: EditorialButtonProps) {
  return renderElement(
    as,
    "a",
    {
      className: cn(
        "group inline-flex min-h-12 items-center justify-center gap-5 border px-7 text-sm tracking-[0.08em] transition duration-300",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring",
        variant === "outline" &&
          "border-border bg-transparent text-foreground hover:border-primary hover:text-primary",
        variant === "solid" &&
          "border-primary bg-primary text-primary-foreground hover:brightness-105",
        variant === "ghost" &&
          "border-transparent bg-transparent text-foreground hover:text-primary",
        className,
      ),
      style: jpFeatureStyle,
      ...props,
    },
    <>
      <span>{children}</span>
      <span aria-hidden="true" className="transition-transform duration-300 group-hover:translate-x-1">
        -&gt;
      </span>
    </>,
  );
}
