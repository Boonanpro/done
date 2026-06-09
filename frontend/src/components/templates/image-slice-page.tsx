"use client";

import * as React from "react";

export type ImageSliceOverlay = {
  id: string;
  rect: {
    top: string;
    left: string;
    width: string;
    height: string;
  };
  content: React.ReactNode;
};

export type ImageSlice = {
  src: string;
  alt: string;
  overlays?: ImageSliceOverlay[];
};

export type ImageSlicePageProps = {
  mobile: ImageSlice[];
  desktop: ImageSlice[];
  mobileMaxWidthClassName?: string;
  desktopMaxWidthClassName?: string;
  className?: string;
  children?: React.ReactNode;
};

function SliceImage({ slice }: { slice: ImageSlice }) {
  const hasOverlays = slice.overlays && slice.overlays.length > 0;

  const image = (
    <img
      src={slice.src}
      alt={slice.alt}
      className="block h-auto w-full select-none"
      draggable={false}
    />
  );

  if (!hasOverlays) {
    return image;
  }

  return (
    <div className="relative -mt-px first:mt-0">
      {image}
      {slice.overlays?.map((overlay) => (
        <div key={overlay.id} className="absolute" style={overlay.rect}>
          {overlay.content}
        </div>
      ))}
    </div>
  );
}

function SliceStack({
  slices,
  className,
}: {
  slices: ImageSlice[];
  className: string;
}) {
  return (
    <div className={className}>
      {slices.map((slice, index) => (
        <SliceImage key={`${slice.src}-${index}`} slice={slice} />
      ))}
    </div>
  );
}

export function ImageSlicePage({
  mobile,
  desktop,
  mobileMaxWidthClassName = "max-w-[480px]",
  desktopMaxWidthClassName = "max-w-[1120px]",
  className = "min-h-screen bg-background text-foreground",
  children,
}: ImageSlicePageProps) {
  return (
    <main className={className}>
      {children}
      <SliceStack
        slices={mobile}
        className={`mx-auto block w-full ${mobileMaxWidthClassName} md:hidden`}
      />
      <SliceStack
        slices={desktop}
        className={`mx-auto hidden w-full ${desktopMaxWidthClassName} md:block`}
      />
    </main>
  );
}
