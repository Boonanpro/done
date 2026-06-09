import * as React from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type CaseStudyItem = {
  title: React.ReactNode;
  description: React.ReactNode;
  image?: string;
  imageAlt?: string;
  href?: string;
  category?: React.ReactNode;
  result?: React.ReactNode;
};

type CaseStudyGridProps = React.HTMLAttributes<HTMLDivElement> & {
  items: CaseStudyItem[];
};

export function CaseStudyGrid({ items, className, ...props }: CaseStudyGridProps) {
  return (
    <div className={cn("grid grid-cols-1 gap-5 md:grid-cols-2", className)} {...props}>
      {items.map((item, index) => {
        const body = (
          <>
            {item.image && (
              <div className="relative aspect-[16/10] overflow-hidden bg-muted">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.image}
                  alt={item.imageAlt ?? ""}
                  className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
                />
              </div>
            )}
            <div className="space-y-4 p-5 sm:p-6">
              <div className="flex items-center justify-between gap-4">
                {item.category && (
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    {item.category}
                  </span>
                )}
                {item.href && <ArrowUpRight className="h-4 w-4 text-muted-foreground" />}
              </div>
              <div className="space-y-2">
                <h3 className="text-xl font-semibold leading-tight text-foreground">
                  {item.title}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {item.description}
                </p>
              </div>
              {item.result && (
                <div className="border-t border-border pt-4 text-sm font-medium text-foreground">
                  {item.result}
                </div>
              )}
            </div>
          </>
        );

        return item.href ? (
          <a
            key={index}
            href={item.href}
            className="group overflow-hidden rounded-md border border-border bg-card transition-colors hover:border-foreground/35"
          >
            {body}
          </a>
        ) : (
          <article
            key={index}
            className="group overflow-hidden rounded-md border border-border bg-card"
          >
            {body}
          </article>
        );
      })}
    </div>
  );
}
