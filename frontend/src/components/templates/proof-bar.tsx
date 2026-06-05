import * as React from "react";
import { cn } from "@/lib/utils";

export type ProofBarItem = {
  value: React.ReactNode;
  label: React.ReactNode;
  note?: React.ReactNode;
};

type ProofBarProps = React.HTMLAttributes<HTMLDivElement> & {
  items: ProofBarItem[];
  variant?: "light" | "dark";
};

export function ProofBar({
  items,
  variant = "light",
  className,
  ...props
}: ProofBarProps) {
  return (
    <div
      className={cn(
        "w-full border-y",
        variant === "dark"
          ? "border-white/12 bg-black text-white"
          : "border-border bg-background text-foreground",
        className,
      )}
      {...props}
    >
      <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-border/70 px-4 sm:grid-cols-4 sm:px-6">
        {items.map((item, index) => (
          <div key={index} className="px-4 py-6 sm:px-6 sm:py-8">
            <div className="text-2xl font-semibold tracking-normal sm:text-3xl">
              {item.value}
            </div>
            <div
              className={cn(
                "mt-1 text-sm",
                variant === "dark" ? "text-white/68" : "text-muted-foreground",
              )}
            >
              {item.label}
            </div>
            {item.note && (
              <div
                className={cn(
                  "mt-2 text-xs leading-relaxed",
                  variant === "dark" ? "text-white/45" : "text-muted-foreground",
                )}
              >
                {item.note}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
