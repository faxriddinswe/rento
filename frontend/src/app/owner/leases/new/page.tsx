"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, errorMessage, unwrap } from "@/lib/api";
import { fmtMoney, somToMinor, todayIso } from "@/lib/format";
import { useT } from "@/i18n";
import { Button, Card, Field, H1, Input } from "@/components/ui";

function Wizard() {
  const { t } = useT();
  const unitId = useSearchParams().get("unit") ?? "";
  const [step, setStep] = useState(1);
  const [f, setF] = useState({ start: todayIso(), end: "", rent: "", deposit: "0", billingDay: "1", dueDays: "10" });
  const [inv, setInv] = useState({ email: "", name: "" });
  const [leaseId, setLeaseId] = useState("");
  const [link, setLink] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function createLease(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const rent = somToMinor(f.rent), deposit = somToMinor(f.deposit || "0");
      if (!Number.isFinite(rent) || !Number.isFinite(deposit)) throw new Error("Summani to'g'ri kiriting");
      const l = unwrap(await api.POST("/units/{unit_id}/leases", {
        params: { path: { unit_id: unitId } },
        body: { start_date: f.start, end_date: f.end || null, monthly_rent: rent, deposit, billing_day: Number(f.billingDay), due_days: Number(f.dueDays) },
      }));
      setLeaseId(l.id);
      setStep(2);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = unwrap(await api.POST("/leases/{lease_id}/invite", { params: { path: { lease_id: leaseId } }, body: { email: inv.email, full_name: inv.name } }));
      setLink(r.url);
      setStep(3);
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <H1>{t("lease.wizardTitle")}</H1>
      <ol className="mb-4 flex gap-2 text-xs">
        {[t("lease.step1"), t("lease.step2"), t("lease.step3")].map((s, i) => (
          <li key={s} className={`flex-1 rounded-full px-2 py-1 text-center ${step === i + 1 ? "bg-emerald-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{i + 1}. {s}</li>
        ))}
      </ol>
      {!unitId && <p role="alert" className="text-rose-600">unit?</p>}
      {step === 1 && (
        <Card>
          <form onSubmit={createLease} className="grid gap-3 sm:grid-cols-2">
            <Field label={t("lease.startDate")}><Input type="date" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
            <Field label={t("lease.endDate")}><Input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
            <Field label={t("lease.rent")}><Input inputMode="decimal" required value={f.rent} onChange={(e) => setF({ ...f, rent: e.target.value })} /></Field>
            <Field label={t("lease.deposit")}><Input inputMode="decimal" value={f.deposit} onChange={(e) => setF({ ...f, deposit: e.target.value })} /></Field>
            <Field label={t("lease.billingDay")}><Input type="number" min={1} max={28} required value={f.billingDay} onChange={(e) => setF({ ...f, billingDay: e.target.value })} /></Field>
            <Field label={t("lease.dueDays")}><Input type="number" min={0} max={60} required value={f.dueDays} onChange={(e) => setF({ ...f, dueDays: e.target.value })} /></Field>
            {f.rent && <p className="text-sm text-slate-500 sm:col-span-2">{fmtMoney(somToMinor(f.rent))}</p>}
            {err && <p role="alert" className="text-sm text-rose-600 sm:col-span-2">{err}</p>}
            <div className="sm:col-span-2"><Button type="submit" disabled={busy || !unitId}>{t("next")}</Button></div>
          </form>
        </Card>
      )}
      {step === 2 && (
        <Card>
          <form onSubmit={invite} className="space-y-3">
            <Field label={t("lease.inviteName")}><Input required value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} /></Field>
            <Field label={t("lease.inviteEmail")}><Input type="email" required value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} /></Field>
            {err && <p role="alert" className="text-sm text-rose-600">{err}</p>}
            <div className="flex gap-2">
              <Button type="submit" disabled={busy}>{t("lease.invite")}</Button>
              <Link href={`/owner/leases/${leaseId}`} className="inline-flex min-h-11 items-center rounded-xl border border-slate-300 px-4 text-sm">{t("lease.skipInvite")}</Link>
            </div>
          </form>
        </Card>
      )}
      {step === 3 && (
        <Card>
          <p className="mb-2 text-sm">{t("lease.inviteLink")}</p>
          <input readOnly value={link} className="mb-3 w-full rounded-xl border border-slate-300 bg-slate-50 p-2 text-sm dark:border-slate-700 dark:bg-slate-900" onFocus={(e) => e.target.select()} />
          <div className="flex gap-2">
            <Button onClick={async () => { await navigator.clipboard.writeText(link); setCopied(true); }}>{copied ? t("lease.copied") : t("lease.copy")}</Button>
            <Link href={`/owner/leases/${leaseId}`} className="inline-flex min-h-11 items-center rounded-xl border border-slate-300 px-4 text-sm">{t("lease.step3")} →</Link>
          </div>
        </Card>
      )}
    </>
  );
}

export default function NewLease() {
  return <Suspense><Wizard /></Suspense>;
}
