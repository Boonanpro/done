"use client";

import * as React from "react";
import Link, { type LinkProps } from "next/link";
import { usePathname } from "next/navigation";
import {
  parseArtifactPath,
  resolveArtifactHref,
} from "@/lib/artifact-paths";

type ArtifactLinkProps = LinkProps &
  Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, keyof LinkProps> & {
    href: LinkProps["href"];
  };

export const ArtifactLink = React.forwardRef<HTMLAnchorElement, ArtifactLinkProps>(
  function ArtifactLink({ href, ...props }, ref) {
    const pathname = usePathname() || "";
    const [hostname, setHostname] = React.useState("");

    React.useEffect(() => {
      setHostname(window.location.hostname);
    }, []);

    const resolvedHref = React.useMemo(() => {
      if (typeof href !== "string") return href;
      const parsed = parseArtifactPath(href);
      if (!parsed) return href;
      return resolveArtifactHref({
        slug: parsed.slug,
        rest: parsed.rest,
        pathname,
        hostname,
      });
    }, [href, hostname, pathname]);

    return <Link ref={ref} href={resolvedHref} {...props} />;
  },
);
