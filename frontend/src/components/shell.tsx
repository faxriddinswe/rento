"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { useT, type Locale } from "@/i18n";
import { Loading } from "./ui";

type NavItem = { href: string; label: string };

export function Shell({ area, nav, children }: { area: "owner" | "tenant"; nav: NavItem[]; children: ReactNode }) {
  const { me, loading, signOut } = useAuth();
  const { t, locale, setLocale } = useT();
  const router = useRouter();
  const path = usePathname();
  const allowed = area === "tenant" ? me?.role === "tenant" : me?.role === "owner" || me?.role === "manager";

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!allowed) router.replace(me.role === "tenant" ? "/tenant" : "/owner");
  }, [loading, me, allowed, router]);

  if (loading || !me || !allowed) return <Loading />;

  return (
    <div className="mx-auto flex min-h-dvh max-w-5xl flex-col">
      <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <Link href={`/${area}`} className="text-lg font-bold text-emerald-700 dark:text-emerald-400">Rento</Link>
        <nav className="hidden gap-1 sm:flex">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={`rounded-lg px-3 py-2 text-sm ${path === n.href ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>{n.label}</Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <select aria-label="Til" value={locale} onChange={(e) => setLocale(e.target.value as Locale)} className="rounded-lg border border-slate-300 bg-transparent px-1 py-1 text-sm dark:border-slate-700">
            <option value="uz">UZ</option><option value="ru">RU</option><option value="en">EN</option>
          </select>
          <button onClick={signOut} className="rounded-lg px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">{t("logout")}</button>
        </div>
      </header>
      <main className="flex-1 px-4 py-5 pb-24 sm:pb-8">{children}</main>
      <nav className="fixed inset-x-0 bottom-0 z-10 grid border-t border-slate-200 bg-white sm:hidden dark:border-slate-800 dark:bg-slate-950" style={{ gridTemplateColumns: `repeat(${nav.length}, minmax(0, 1fr))` }}>
        {nav.map((n) => (
          <Link key={n.href} href={n.href} className={`px-1 py-3 text-center text-xs ${path === n.href ? "font-semibold text-emerald-700 dark:text-emerald-400" : "text-slate-600 dark:text-slate-400"}`}>{n.label}</Link>
        ))}
      </nav>
    </div>
  );
}
