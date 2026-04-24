import * as React from "react";
import { cn } from "@/lib/utils";

type SectionProps = React.HTMLAttributes<HTMLElement> & {
  width?: "sm" | "md" | "lg" | "xl" | "full";
  padding?: "sm" | "md" | "lg" | "xl";
  as?: "section" | "div" | "article";
  eyebrow?: React.ReactNode;
  heading?: React.ReactNode;
  description?: React.ReactNode;
  align?: "left" | "center";
};

const WIDTH_MAP: Record<NonNullable<SectionProps["width"]>, string> = {
  sm: "max-w-2xl",
  md: "max-w-4xl",
  lg: "max-w-6xl",
  xl: "max-w-7xl",
  full: "",
};

const PADDING_MAP: Record<NonNullable<SectionProps["padding"]>, string> = {
  sm: "py-10 sm:py-14",
  md: "py-14 sm:py-20",
  lg: "py-20 sm:py-28",
  xl: "py-28 sm:py-36",
};

export function Section({
  width = "lg",
  padding = "md",
  as = "section",
  eyebrow,
  heading,
  description,
  align = "left",
  className,
  children,
  ...props
}: SectionProps) {
  const Tag = as;
  const hasHeader = eyebrow || heading || description;
  return (
    <Tag className={cn("w-full", PADDING_MAP[padding], className)} {...props}>
      <div
        className={cn(
          WIDTH_MAP[width],
          width !== "full" && "mx-auto",
          "px-4 sm:px-6",
        )}
      >
        {hasHeader && (
          <div
            className={cn(
              "space-y-3 mb-10 sm:mb-14",
              align === "center" && "text-center mx-auto max-w-2xl",
            )}
          >
            {eyebrow && (
              <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {eyebrow}
              </div>
            )}
            {heading && (
              <h2 className="text-3xl sm:text-4xl font-semibold text-foreground tracking-tight">
                {heading}
              </h2>
            )}
            {description && (
              <p className="text-base text-muted-foreground leading-relaxed">
                {description}
              </p>
            )}
          </div>
        )}
        {children}
      </div>
    </Tag>
  );
}
