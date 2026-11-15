"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { uz, type Dict } from "./uz";
import { ru } from "./ru";
import { en } from "./en";

export type Locale = "uz" | "ru" | "en";
const bundles: Record<Locale, Record<string, unknown>> = { uz, ru, en };

function lookup(obj: unknown, path: string[]): string | undefined {
  let cur: unknown = obj;
  for (const p of path) {
    if (cur && typeof cur === "object" && p in (cur as Record<string, unknown>)) cur = (cur as Record<string, unknown>)[p];
    else return undefined;
  }
  return typeof cur === "string" ? cur : undefined;
}

type Ctx = { locale: Locale; setLocale: (l: Locale) => void; t: (key: string) => string };
const I18nContext = createContext<Ctx>({ locale: "uz", setLocale: () => {}, t: (k) => k });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("uz");
  useEffect(() => {
    try {
      const saved = localStorage.getItem("rento.locale") as Locale | null;
      if (saved && saved in bundles) setLocaleState(saved);
    } catch {}
  }, []);
  const setLocale = (l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem("rento.locale", l);
    } catch {}
  };
  const t = (key: string) => {
    const path = key.split(".");
    return lookup(bundles[locale], path) ?? lookup(uz, path) ?? key;
  };
  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>;
}

export const useT = () => useContext(I18nContext);
export type { Dict };
