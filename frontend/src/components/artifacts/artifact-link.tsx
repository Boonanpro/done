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

const DedicatedArtifactSlugContext = React.createContext<string | null>(null);

/**
 * 専用配信プロジェクトが配信している成果物の slug を、サーバー描画の時点からリンクへ伝える。
 * ホスト名はブラウザに届くまで分からないので、これが無いと最初の HTML のリンクだけ
 * `/preview/<slug>/...` になる（artifacts/layout.tsx が ARTIFACT_ONLY_SLUG を渡す）。
 */
export function DedicatedArtifactProvider({
  slug,
  children,
}: {
  slug: string | null;
  children: React.ReactNode;
}) {
  return (
    <DedicatedArtifactSlugContext.Provider value={slug}>
      {children}
    </DedicatedArtifactSlugContext.Provider>
  );
}

export const ArtifactLink = React.forwardRef<HTMLAnchorElement, ArtifactLinkProps>(
  function ArtifactLink({ href, ...props }, ref) {
    const pathname = usePathname() || "";
    const dedicatedSlug = React.useContext(DedicatedArtifactSlugContext);
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
        dedicatedSlug,
      });
    }, [dedicatedSlug, href, hostname, pathname]);

    return <Link ref={ref} href={resolvedHref} {...props} />;
  },
);
