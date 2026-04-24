import * as React from "react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";

type KpiCardProps = {
  label: React.ReactNode;
  value: React.ReactNode;
  icon?: React.ReactNode;
  trend?: {
    value: React.ReactNode;
    direction: "up" | "down" | "flat";
    label?: React.ReactNode;
  };
  hint?: React.ReactNode;
  className?: string;
};

const TREND_COLOR = {
  up: "text-emerald-500",
  down: "text-rose-500",
  flat: "text-muted-foreground",
} as const;

export function KpiCard({
  label,
  value,
  icon,
  trend,
  hint,
  className,
}: KpiCardProps) {
  return (
    <Card className={className}>
      <CardContent className="pt-6 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">{label}</span>
          {icon && (
            <span className="text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
              {icon}
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl sm:text-3xl font-semibold tabular-nums text-foreground">
            {value}
          </span>
          {trend && (
            <span
              className={cn(
                "text-xs font-medium tabular-nums",
                TREND_COLOR[trend.direction],
              )}
            >
              {trend.direction === "up" && "▲ "}
              {trend.direction === "down" && "▼ "}
              {trend.value}
              {trend.label && (
                <span className="text-muted-foreground ml-1">{trend.label}</span>
              )}
            </span>
          )}
        </div>
        {hint && (
          <div className="text-xs text-muted-foreground">{hint}</div>
        )}
      </CardContent>
    </Card>
  );
}
