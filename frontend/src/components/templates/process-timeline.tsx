import * as React from "react";
import { cn } from "@/lib/utils";

export type ProcessStep = {
  title: React.ReactNode;
  description: React.ReactNode;
  meta?: React.ReactNode;
};

type ProcessTimelineProps = React.HTMLAttributes<HTMLDivElement> & {
  steps: ProcessStep[];
};

export function ProcessTimeline({ steps, className, ...props }: ProcessTimelineProps) {
  return (
    <div className={cn("space-y-0", className)} {...props}>
      {steps.map((step, index) => (
        <div key={index} className="grid grid-cols-[auto_1fr] gap-5">
          <div className="flex flex-col items-center">
            <div className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-background text-sm font-semibold tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </div>
            {index < steps.length - 1 && <div className="h-full min-h-12 w-px bg-border" />}
          </div>
          <div className="pb-9">
            {step.meta && (
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {step.meta}
              </div>
            )}
            <h3 className="text-lg font-semibold leading-tight text-foreground">
              {step.title}
            </h3>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {step.description}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
