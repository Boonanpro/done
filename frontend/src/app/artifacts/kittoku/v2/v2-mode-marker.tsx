"use client";

import * as React from "react";

/**
 * v2 ページ訪問時に sessionStorage に "v2" を記録する。
 * SiteNav はこれを読んで「ホーム」リンクを v2 に切り替える。
 */
export function V2ModeMarker() {
  React.useEffect(() => {
    try {
      sessionStorage.setItem("kittoku-mode", "v2");
    } catch {
      /* ignore */
    }
  }, []);
  return null;
}
