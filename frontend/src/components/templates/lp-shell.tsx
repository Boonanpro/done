import * as React from "react";
import { cn } from "@/lib/utils";

type LpShellProps = React.HTMLAttributes<HTMLDivElement> & {
  nav?: React.ReactNode;
  footer?: React.ReactNode;
  stickyNav?: boolean;
};

export function LpShell({
  nav,
  footer,
  stickyNav = true,
  className,
  children,
  ...props
}: LpShellProps) {
  return (
    <div
      className={cn(
        "min-h-screen bg-background text-foreground flex flex-col",
        className,
      )}
      {...props}
    >
      {nav && (
        <header
          className={cn(
            "w-full border-b border-border/60 bg-background/80 backdrop-blur",
            stickyNav && "sticky top-0 z-40",
          )}
        >
          {nav}
        </header>
      )}
      <main className="flex-1">{children}</main>
      {footer && (
        <footer className="border-t border-border/60 bg-background">
          {footer}
        </footer>
      )}
    </div>
  );
}
