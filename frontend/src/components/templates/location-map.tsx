import * as React from "react";
import { cn } from "@/lib/utils";
import { MapPin } from "lucide-react";

type LocationMapProps = {
  src: string;
  address?: React.ReactNode;
  caption?: React.ReactNode;
  aspectRatio?: "16/9" | "4/3" | "1/1" | "21/9";
  height?: number;
  rounded?: boolean;
  className?: string;
};

const ASPECT_MAP: Record<NonNullable<LocationMapProps["aspectRatio"]>, string> = {
  "16/9": "aspect-[16/9]",
  "4/3": "aspect-[4/3]",
  "1/1": "aspect-square",
  "21/9": "aspect-[21/9]",
};

export function LocationMap({
  src,
  address,
  caption,
  aspectRatio = "16/9",
  height,
  rounded = true,
  className,
}: LocationMapProps) {
  return (
    <div className={cn("space-y-3", className)}>
      <div
        className={cn(
          "relative overflow-hidden border border-border/60 bg-muted",
          rounded && "rounded-xl",
          height ? "" : ASPECT_MAP[aspectRatio],
        )}
        style={height ? { height } : undefined}
      >
        <iframe
          src={src}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          allowFullScreen
          className="absolute inset-0 h-full w-full border-0"
          title={typeof address === "string" ? address : "Location map"}
        />
      </div>
      {(address || caption) && (
        <div className="flex items-start gap-2 text-sm">
          <MapPin className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div className="space-y-0.5">
            {address && (
              <div className="text-foreground font-medium">{address}</div>
            )}
            {caption && (
              <div className="text-muted-foreground">{caption}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
