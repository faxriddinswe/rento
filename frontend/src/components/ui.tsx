"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useT } from "@/i18n";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}>{children}</div>;
}

export function H1({ children }: { children: ReactNode }) {
  return <h1 className="mb-4 text-xl font-semibold tracking-tight sm:text-2xl">{children}</h1>;
}
export function H2({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-base font-semibold sm:text-lg">{children}</h2>;
}

export function Button({ variant = "primary", className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = {
    primary: "bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300",
    ghost: "border border-slate-300 bg-transparent hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  }[variant];
  return <button className={`min-h-11 rounded-xl px-4 py-2 text-sm font-medium transition ${v} ${className}`} {...p} />;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600 dark:text-slate-400">{label}</span>
      {children}
    </label>
  );
}
const inputCls = "min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-base dark:border-slate-700 dark:bg-slate-950";
export function Input(p: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={inputCls} {...p} />;
}
export function Select(p: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={inputCls} {...p} />;
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "red" | "amber" }) {
  const c = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
    red: "bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-200",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  }[tone];
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${c}`}>{children}</span>;
}

export function Loading() {
  const { t } = useT();
  return <p className="py-8 text-center text-slate-500" role="status">{t("loading")}</p>;
}
export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const { t } = useT();
  return (
    <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-rose-800 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-200">
      <p className="font-medium">{t("error")}</p>
      <p className="text-sm">{error instanceof Error ? error.message : String(error)}</p>
      {retry && <Button variant="ghost" className="mt-2" onClick={retry}>{t("retry")}</Button>}
    </div>
  );
}
export function Empty({ children }: { children?: ReactNode }) {
  const { t } = useT();
  return <p className="py-6 text-center text-slate-500">{children ?? t("empty")}</p>;
}

/** Render loading / error / empty / content for a TanStack query result. */
export function QueryState<T>({ q, children, isEmpty }: {
  q: { isLoading: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown };
  children: (data: T) => ReactNode;
  isEmpty?: (d: T) => boolean;
}) {
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} retry={() => void q.refetch()} />;
  if (q.data === undefined) return null;
  if (isEmpty?.(q.data)) return <Empty />;
  return <>{children(q.data)}</>;
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b border-slate-200 text-slate-500 dark:border-slate-800">{head.map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
export const Td = ({ children, right }: { children?: ReactNode; right?: boolean }) => (
  <td className={`border-b border-slate-100 px-2 py-2 align-top dark:border-slate-800 ${right ? "text-right tabular-nums" : ""}`}>{children}</td>
);
