"use client";

import * as React from "react";

export type Lang = "ja" | "en";

const LangCtx = React.createContext<{
  lang: Lang;
  setLang: (l: Lang) => void;
}>({ lang: "ja", setLang: () => {} });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = React.useState<Lang>("ja");

  React.useEffect(() => {
    const saved = localStorage.getItem("paina-lang");
    if (saved === "en" || saved === "ja") setLangState(saved);
  }, []);

  const setLang = React.useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("paina-lang", l);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l;
  }, []);

  React.useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return (
    <LangCtx.Provider value={{ lang, setLang }}>{children}</LangCtx.Provider>
  );
}

export function useLang() {
  return React.useContext(LangCtx);
}

/** {ja, en} の組から現在の言語の値を取り出す小ヘルパー。 */
export function pick<T>(lang: Lang, pair: { ja: T; en: T }): T {
  return pair[lang];
}
