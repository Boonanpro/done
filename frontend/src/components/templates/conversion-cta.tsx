import * as React from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type ConversionCtaProps = React.HTMLAttributes<HTMLElement> & {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  primaryLabel: React.ReactNode;
  primaryHref: string;
  secondaryLabel?: React.ReactNode;
  secondaryHref?: string;
  image?: string;
  imageAlt?: string;
};

export function ConversionCta({
  eyebrow,
  title,
  description,
  primaryLabel,
  primaryHref,
  secondaryLabel,
  secondaryHref,
  image,
  imageAlt,
  className,
  ...props
}: ConversionCtaProps) {
  return (
    <section className={cn("w-full bg-foreground text-background", className)} {...props}>
      <div className="mx-auto grid max-w-7xl grid-cols-1 items-stretch gap-0 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-2">
        <div className="flex flex-col justify-center py-4 lg:pr-14">
          {eyebrow && (
            <div className="mb-4 text-xs font-semibold uppercase tracking-[0.18em] opacity-60">
              {eyebrow}
            </div>
          )}
          <h2 className="text-balance text-3xl font-semibold leading-tight tracking-normal sm:text-5xl">
            {title}
          </h2>
          {description && (
            <p className="mt-5 max-w-2xl text-base leading-relaxed opacity-70">
              {description}
            </p>
          )}
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg" className="bg-background text-foreground hover:bg-background/90">
              <a href={primaryHref}>
                {primaryLabel}
                <ArrowRight className="ml-2 h-4 w-4" />
              </a>
            </Button>
            {secondaryLabel && secondaryHref && (
              <Button asChild size="lg" variant="outline" className="border-background/30 text-background hover:bg-background/10">
                <a href={secondaryHref}>{secondaryLabel}</a>
              </Button>
            )}
          </div>
        </div>
        {image && (
          <div className="relative mt-10 min-h-[280px] overflow-hidden rounded-md bg-background/10 lg:mt-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image} alt={imageAlt ?? ""} className="absolute inset-0 h-full w-full object-cover" />
          </div>
        )}
      </div>
    </section>
  );
}
