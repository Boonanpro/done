import * as React from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type ServiceShowcaseItem = {
  title: React.ReactNode;
  description: React.ReactNode;
  image?: string;
  imageAlt?: string;
  icon?: React.ReactNode;
  href?: string;
  meta?: React.ReactNode;
};

type ServiceShowcaseProps = React.HTMLAttributes<HTMLDivElement> & {
  items: ServiceShowcaseItem[];
  featuredIndex?: number;
};

export function ServiceShowcase({
  items,
  featuredIndex = 0,
  className,
  ...props
}: ServiceShowcaseProps) {
  return (
    <div className={cn("grid grid-cols-1 gap-4 lg:grid-cols-3", className)} {...props}>
      {items.map((item, index) => {
        const featured = index === featuredIndex;
        const content = (
          <>
            {item.image && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.image}
                alt={item.imageAlt ?? ""}
                className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
              />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-black/82 via-black/22 to-transparent" />
            <div className="relative z-10 flex h-full flex-col justify-end p-5 sm:p-7">
              <div className="mb-4 flex items-center gap-3">
                {item.icon && (
                  <span className="flex h-10 w-10 items-center justify-center rounded-md bg-white/12 text-white backdrop-blur [&>svg]:h-5 [&>svg]:w-5">
                    {item.icon}
                  </span>
                )}
                {item.meta && <span className="text-xs font-medium uppercase tracking-[0.14em] text-white/58">{item.meta}</span>}
              </div>
              <h3 className={cn("font-semibold leading-tight text-white", featured ? "text-2xl sm:text-3xl" : "text-xl")}>
                {item.title}
              </h3>
              <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/72">
                {item.description}
              </p>
              {item.href && (
                <div className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-white">
                  View details
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </div>
              )}
            </div>
          </>
        );

        return item.href ? (
          <a
            key={index}
            href={item.href}
            className={cn(
              "group relative block overflow-hidden rounded-md bg-card",
              featured ? "min-h-[420px] lg:col-span-2" : "min-h-[300px]",
            )}
          >
            {content}
          </a>
        ) : (
          <div
            key={index}
            className={cn(
              "group relative overflow-hidden rounded-md bg-card",
              featured ? "min-h-[420px] lg:col-span-2" : "min-h-[300px]",
            )}
          >
            {content}
          </div>
        );
      })}
    </div>
  );
}
