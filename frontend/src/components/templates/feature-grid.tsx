import * as React from "react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";

export type FeatureItem = {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  href?: string;
};

type FeatureGridProps = React.HTMLAttributes<HTMLDivElement> & {
  items: FeatureItem[];
  columns?: 2 | 3 | 4;
  variant?: "card" | "bare";
};

const COLUMN_MAP: Record<NonNullable<FeatureGridProps["columns"]>, string> = {
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
};

export function FeatureGrid({
  items,
  columns = 3,
  variant = "card",
  className,
  ...props
}: FeatureGridProps) {
  return (
    <div
      className={cn("grid gap-4 sm:gap-6", COLUMN_MAP[columns], className)}
      {...props}
    >
      {items.map((item, i) => {
        const body = (
          <>
            {item.icon && (
              <div className="text-foreground/80 [&>svg]:h-6 [&>svg]:w-6">
                {item.icon}
              </div>
            )}
            <div className="space-y-2">
              <h3 className="text-base sm:text-lg font-semibold text-foreground">
                {item.title}
              </h3>
              {item.description && (
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {item.description}
                </p>
              )}
            </div>
          </>
        );

        if (variant === "card") {
          return (
            <Card key={i} className="h-full">
              <CardContent className="pt-6 space-y-4">{body}</CardContent>
            </Card>
          );
        }

        return (
          <div key={i} className="space-y-4">
            {body}
          </div>
        );
      })}
    </div>
  );
}
