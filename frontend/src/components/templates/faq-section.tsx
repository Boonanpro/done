import * as React from "react";
import { cn } from "@/lib/utils";

export type FaqItem = {
  question: React.ReactNode;
  answer: React.ReactNode;
};

type FaqSectionProps = React.HTMLAttributes<HTMLDivElement> & {
  items: FaqItem[];
};

export function FaqSection({ items, className, ...props }: FaqSectionProps) {
  return (
    <div className={cn("divide-y divide-border rounded-md border border-border", className)} {...props}>
      {items.map((item, index) => (
        <details key={index} className="group bg-background open:bg-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-5 px-5 py-5 text-base font-medium text-foreground sm:px-6">
            {item.question}
            <span className="relative h-4 w-4 shrink-0 text-muted-foreground">
              <span className="absolute left-0 top-1/2 h-px w-4 bg-current" />
              <span className="absolute left-1/2 top-0 h-4 w-px bg-current transition-transform group-open:rotate-90" />
            </span>
          </summary>
          <div className="px-5 pb-5 text-sm leading-relaxed text-muted-foreground sm:px-6">
            {item.answer}
          </div>
        </details>
      ))}
    </div>
  );
}
