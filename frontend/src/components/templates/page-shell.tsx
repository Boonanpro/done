import * as React from "react";
import { cn } from "@/lib/utils";

type PageShellProps = React.HTMLAttributes<HTMLDivElement> & {
  width?: "sm" | "md" | "lg" | "xl" | "full";
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
};

const WIDTH_MAP: Record<NonNullable<PageShellProps["width"]>, string> = {
  sm: "max-w-2xl",
  md: "max-w-4xl",
  lg: "max-w-6xl",
  xl: "max-w-7xl",
  full: "",
};

export function PageShell({
  width = "lg",
  title,
  description,
  actions,
  className,
  children,
  ...props
}: PageShellProps) {
  const hasHeader = title || description || actions;
  return (
    <div
      className={cn(
        WIDTH_MAP[width],
        width !== "full" && "mx-auto",
        "px-4 sm:px-6 py-6 sm:py-8 space-y-6",
        className,
      )}
      {...props}
    >
      {hasHeader && (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="space-y-1">
            {title && (
              <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
            )}
            {description && (
              <p className="text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {actions && <div className="flex gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
