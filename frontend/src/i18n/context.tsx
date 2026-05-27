import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import zh from "./zh.json";
import en from "./en.json";

export type Lang = "zh" | "en";

const translations: Record<Lang, Record<string, string>> = { zh, en };

const LangContext = createContext<{
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, fallback?: string) => string;
}>({
  lang: "zh",
  setLang: () => {},
  t: (k, fb) => fb ?? k,
});

function getInitialLang(): Lang {
  try {
    const stored = localStorage.getItem("app-lang");
    if (stored === "zh" || stored === "en") return stored;
  } catch {}
  return "zh";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(getInitialLang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem("app-lang", l); } catch {}
  }, []);

  const t = useCallback(
    (key: string, fallback?: string) => {
      return translations[lang][key] ?? fallback ?? key;
    },
    [lang],
  );

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useT() {
  return useContext(LangContext);
}
