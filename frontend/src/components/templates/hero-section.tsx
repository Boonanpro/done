import * as React from "react";
import { cn } from "@/lib/utils";

type HeroSectionProps = React.HTMLAttributes<HTMLElement> & {
  eyebrow?: React.ReactNode;
  heading: React.ReactNode;
  subheading?: React.ReactNode;
  actions?: React.ReactNode;
  media?: React.ReactNode;
  layout?: "split" | "centered" | "stacked";
  mediaPosition?: "right" | "left";
  background?: React.ReactNode;
};

export function HeroSection({
  eyebrow,
  heading,
  subheading,
  actions,
  media,
  layout = "split",
  mediaPosition = "right",
  background,
  className,
  ...props
}: HeroSectionProps) {
  if (layout === "centered") {
    return (
      <section
        className={cn(
          "relative w-full overflow-hidden py-20 sm:py-28 lg:py-36",
          className,
        )}
        {...props}
      >
        {background && <div className="absolute inset-0 -z-10">{background}</div>}
        <div className="relative mx-auto max-w-4xl px-4 sm:px-6 text-center space-y-6">
          {eyebrow && (
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              {eyebrow}
            </div>
          )}
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold text-foreground tracking-tight leading-tight">
            {heading}
          </h1>
          {subheading && (
            <p className="text-lg text-muted-foreground leading-relaxed max-w-2xl mx-auto">
              {subheading}
            </p>
          )}
          {actions && (
            <div className="flex flex-wrap justify-center gap-3 pt-2">
              {actions}
            </div>
          )}
          {media && <div className="pt-10">{media}</div>}
        </div>
      </section>
    );
  }

  if (layout === "stacked") {
    return (
      <section
        className={cn("relative w-full overflow-hidden", className)}
        {...props}
      >
        {background && <div className="absolute inset-0 -z-10">{background}</div>}
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6 py-20 sm:py-28">
          <div className="max-w-3xl space-y-6">
            {eyebrow && (
              <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {eyebrow}
              </div>
            )}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold text-foreground tracking-tight leading-tight">
              {heading}
            </h1>
            {subheading && (
              <p className="text-lg text-muted-foreground leading-relaxed">
                {subheading}
              </p>
            )}
            {actions && <div className="flex flex-wrap gap-3 pt-2">{actions}</div>}
          </div>
          {media && <div className="mt-12 sm:mt-16">{media}</div>}
        </div>
      </section>
    );
  }

  return (
    <section
      className={cn("relative w-full overflow-hidden", className)}
      {...props}
    >
      {background && <div className="absolute inset-0 -z-10">{background}</div>}
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 py-20 sm:py-28 lg:py-32">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div
            className={cn(
              "space-y-6",
              mediaPosition === "left" && "lg:order-2",
            )}
          >
            {eyebrow && (
              <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {eyebrow}
              </div>
            )}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold text-foreground tracking-tight leading-tight">
              {heading}
            </h1>
            {subheading && (
              <p className="text-lg text-muted-foreground leading-relaxed">
                {subheading}
              </p>
            )}
            {actions && <div className="flex flex-wrap gap-3 pt-2">{actions}</div>}
          </div>
          {media && (
            <div
              className={cn(
                "relative",
                mediaPosition === "left" && "lg:order-1",
              )}
            >
              {media}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
