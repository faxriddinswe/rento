"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, openPdf, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtMoney, somToMinor, todayIso } from "@/lib/format";
import { useT } from "@/i18n";
import { Badge, Button, Card, Field, H1, H2, Input, QueryState, Select, Table, Td } from "@/components/ui";

const Err = ({ e }: { e: unknown }) => (e ? <p role="alert" className="text-sm text-rose-600">{errorMessage(e)}</p> : null);

function useRefresh(id: string) {
  const qc = useQueryClient();
  return () => {
    for (const k of ["balance", "invoices", "payments", "ledger", "lease", "documents", "dashboard"]) void qc.invalidateQueries({ queryKey: [k, id] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
}

function Balance({ id }: { id: string }) {
  const { t } = useT();
  const q = useQuery({ queryKey: ["balance", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/balance", { params: { path: { lease_id: id } } })) });
  return (
    <QueryState q={q}>
      {(b) => (
        <div className="grid grid-cols-3 gap-3">
          <Card><p className="text-xs text-slate-500">{t("lease.owes")}</p><p className={`text-lg font-semibold tabular-nums ${b.owed ? "text-rose-600" : ""}`}>{fmtMoney(b.owed)}</p></Card>
          <Card><p className="text-xs text-slate-500">{t("lease.credit")}</p><p className="text-lg font-semibold tabular-nums text-emerald-600">{fmtMoney(b.credit)}</p></Card>
          <Card><p className="text-xs text-slate-500">{t("lease.overdue")}</p><p className={`text-lg font-semibold tabular-nums ${b.overdue ? "text-rose-600" : ""}`}>{fmtMoney(b.overdue)}</p></Card>
        </div>
      )}
    </QueryState>
  );
}

function Invoices({ id, canVoid }: { id: string; canVoid: boolean }) {
  const { t } = useT();
  const refresh = useRefresh(id);
  const q = useQuery({ queryKey: ["invoices", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/invoices", { params: { path: { lease_id: id } } })) });
  const voidInv = useMutation({
    mutationFn: async (inv: string) => unwrap(await api.POST("/invoices/{invoice_id}/void", { params: { path: { invoice_id: inv } }, body: { reason: "Owner void" } })),
    onSuccess: refresh,
  });
  return (
    <Card>
      <H2>{t("lease.invoices")}</H2>
      <QueryState q={q} isEmpty={(d) => d.length === 0}>
        {(rows) => (
          <div className="space-y-3">
            {rows.map((i) => (
              <details key={i.id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2">
                  <span><b>{i.number}</b> · {fmtDate(i.period_start)}–{fmtDate(i.period_end)}</span>
                  <span className="flex items-center gap-2"><span className="tabular-nums">{fmtMoney(i.total)}</span>
                    {i.status === "void" ? <Badge tone="red">{t("lease.void2")}</Badge> : i.remaining === 0 ? <Badge tone="green">{t("lease.paid")}</Badge> : <Badge tone="amber">{t("lease.remaining")}: {fmtMoney(i.remaining)}</Badge>}</span>
                </summary>
                <Table head={[t("name"), t("amount")]}>
                  {i.lines.map((l) => <tr key={l.id}><Td>{l.pending_reading ? <i className="text-amber-700">{l.description}</i> : l.description}</Td><Td right>{fmtMoney(l.amount)}</Td></tr>)}
                </Table>
                <p className="mt-2 text-xs text-slate-500">{t("lease.due")}: {fmtDate(i.due_date)}</p>
                <div className="mt-2 flex gap-2">
                  <Button variant="ghost" onClick={() => void openPdf(`/invoices/${i.id}/pdf`)}>{t("download")}</Button>
                  {canVoid && i.status === "issued" && <Button variant="danger" onClick={() => voidInv.mutate(i.id)}>{t("lease.void")}</Button>}
                </div>
              </details>
            ))}
            <Err e={voidInv.error} />
          </div>
        )}
      </QueryState>
    </Card>
  );
}

function Payments({ id, canReverse }: { id: string; canReverse: boolean }) {
  const { t } = useT();
  const refresh = useRefresh(id);
  const q = useQuery({ queryKey: ["payments", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/payments", { params: { path: { lease_id: id } } })) });
  const [f, setF] = useState({ amount: "", date: todayIso(), method: "cash" as "cash" | "card" | "transfer" | "other", ref: "" });
  const pay = useMutation({
    mutationFn: async () => {
      const amount = somToMinor(f.amount);
      if (!Number.isFinite(amount) || amount <= 0) throw new Error("Summani to'g'ri kiriting");
      return unwrap(await api.POST("/leases/{lease_id}/payments", { params: { path: { lease_id: id } }, body: { amount, paid_on: f.date, method: f.method, reference: f.ref || null } }));
    },
    onSuccess: () => { setF({ ...f, amount: "", ref: "" }); refresh(); },
  });
  const reverse = useMutation({
    mutationFn: async (pid: string) => unwrap(await api.POST("/payments/{payment_id}/reverse", { params: { path: { payment_id: pid } }, body: { reason: "Owner reversal" } })),
    onSuccess: refresh,
  });
  return (
    <Card>
      <H2>{t("lease.payments")}</H2>
      <form className="mb-4 grid gap-3 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); pay.mutate(); }}>
        <Field label={t("amount")}><Input inputMode="decimal" required value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label={t("date")}><Input type="date" required value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label={t("lease.method")}><Select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value as typeof f.method })}>{(["cash", "card", "transfer", "other"] as const).map((m) => <option key={m} value={m}>{t(`lease.methods.${m}`)}</option>)}</Select></Field>
        <Field label={t("lease.reference")}><Input value={f.ref} onChange={(e) => setF({ ...f, ref: e.target.value })} /></Field>
        <div className="flex items-end"><Button type="submit" disabled={pay.isPending} className="w-full">{t("lease.recordPayment")}</Button></div>
      </form>
      <Err e={pay.error} /><Err e={reverse.error} />
      <QueryState q={q} isEmpty={(d) => d.length === 0}>
        {(rows) => (
          <Table head={[t("date"), t("amount"), t("lease.method"), t("lease.allocated"), ""]}>
            {rows.map((p) => (
              <tr key={p.id} className={p.reversed_at ? "opacity-50 line-through" : ""}>
                <Td>{fmtDate(p.paid_on)}</Td><Td right>{fmtMoney(p.amount)}</Td><Td>{t(`lease.methods.${p.method}`)}</Td>
                <Td right>{fmtMoney(p.allocated)}{p.credit > 0 && <Badge tone="green"> +{fmtMoney(p.credit)}</Badge>}</Td>
                <Td>{canReverse && !p.reversed_at && <Button variant="ghost" onClick={() => reverse.mutate(p.id)}>{t("lease.reverse")}</Button>}</Td>
              </tr>
            ))}
          </Table>
        )}
      </QueryState>
    </Card>
  );
}

function Ledger({ id }: { id: string }) {
  const { t } = useT();
  const q = useQuery({ queryKey: ["ledger", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/ledger", { params: { path: { lease_id: id } } })) });
  return (
    <Card>
      <H2>{t("lease.ledger")}</H2>
      <QueryState q={q} isEmpty={(d) => d.length === 0}>
        {(rows) => (
          <Table head={[t("date"), t("name"), t("amount"), t("lease.balance")]}>
            {[...rows].reverse().map((e) => (
              <tr key={e.id}><Td>{fmtDate(e.created_at)}</Td><Td>{e.description || e.entry_type}</Td><Td right><span className={e.amount < 0 ? "text-emerald-600" : ""}>{fmtMoney(e.amount)}</span></Td><Td right>{fmtMoney(e.running_balance)}</Td></tr>
            ))}
          </Table>
        )}
      </QueryState>
    </Card>
  );
}

function Tools({ id, hasTenant, ended }: { id: string; hasTenant: boolean; ended: boolean }) {
  const { t } = useT();
  const refresh = useRefresh(id);
  const [adj, setAdj] = useState({ amount: "", note: "" });
  const [inv, setInv] = useState({ email: "", name: "" });
  const [link, setLink] = useState("");
  const [endDate, setEndDate] = useState(todayIso());
  const docs = useQuery({ queryKey: ["documents", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/documents", { params: { path: { lease_id: id } } })) });
  const run = useMutation({ mutationFn: async () => unwrap(await api.POST("/leases/{lease_id}/billing/run", { params: { path: { lease_id: id } }, body: {} })), onSuccess: refresh });
  const addAdj = useMutation({
    mutationFn: async () => unwrap(await api.POST("/leases/{lease_id}/adjustments", { params: { path: { lease_id: id } }, body: { amount: somToMinor(adj.amount), description: adj.note } })),
    onSuccess: () => setAdj({ amount: "", note: "" }),
  });
  const contract = useMutation({ mutationFn: async () => unwrap(await api.POST("/leases/{lease_id}/contract", { params: { path: { lease_id: id } } })), onSuccess: refresh });
  const invite = useMutation({
    mutationFn: async () => unwrap(await api.POST("/leases/{lease_id}/invite", { params: { path: { lease_id: id } }, body: { email: inv.email, full_name: inv.name } })),
    onSuccess: (r) => setLink(r.url),
  });
  const end = useMutation({ mutationFn: async () => unwrap(await api.POST("/leases/{lease_id}/end", { params: { path: { lease_id: id } }, body: { end_date: endDate } })), onSuccess: refresh });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <H2>{t("lease.adjustments")}</H2>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); addAdj.mutate(); }}>
          <Field label={t("lease.adjAmount")}><Input inputMode="decimal" required value={adj.amount} onChange={(e) => setAdj({ ...adj, amount: e.target.value })} /></Field>
          <Field label={t("lease.adjNote")}><Input required value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} /></Field>
          <Err e={addAdj.error} />{addAdj.isSuccess && <p className="text-sm text-emerald-600">✓</p>}
          <Button type="submit">{t("add")}</Button>
        </form>
        <hr className="my-4" />
        <Button variant="ghost" onClick={() => run.mutate()} disabled={run.isPending}>{t("lease.runBilling")}</Button>
        {run.data && <p className="mt-2 text-sm">+{run.data.created} / ={run.data.exists}</p>}
        <Err e={run.error} />
      </Card>
      <Card>
        <H2>{t("lease.contract")}</H2>
        <Button onClick={() => contract.mutate()} disabled={contract.isPending}>{t("lease.makeContract")}</Button>
        <Err e={contract.error} />
        <ul className="mt-3 space-y-1 text-sm">
          {docs.data?.filter((d) => d.kind === "contract").map((d) => (
            <li key={d.id}><button className="text-emerald-700 underline" onClick={() => void openPdf(`/documents/${d.id}/download`)}>v{d.version}</button> · {fmtDate(d.created_at)}</li>
          ))}
        </ul>
        {!hasTenant && (
          <>
            <hr className="my-4" />
            <H2>{t("lease.noTenant")}</H2>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
              <Input required placeholder={t("lease.inviteName")} value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} />
              <Input type="email" required placeholder={t("lease.inviteEmail")} value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />
              <Err e={invite.error} />
              {link && <input readOnly value={link} className="w-full rounded-xl border p-2 text-sm" onFocus={(e) => e.target.select()} />}
              <Button type="submit">{t("lease.invite")}</Button>
            </form>
          </>
        )}
        {!ended && (
          <>
            <hr className="my-4" />
            <div className="flex items-end gap-2">
              <Field label={t("lease.endDate2")}><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></Field>
              <Button variant="danger" onClick={() => end.mutate()} disabled={end.isPending}>{t("lease.end")}</Button>
            </div>
            <Err e={end.error} />
          </>
        )}
      </Card>
    </div>
  );
}

export default function LeasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { t } = useT();
  const { me } = useAuth();
  const lease = useQuery({ queryKey: ["lease", id], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}", { params: { path: { lease_id: id } } })) });
  const isOwner = me?.role === "owner";
  return (
    <div className="space-y-4">
      <QueryState q={lease}>
        {(l) => (
          <>
            <H1>{fmtMoney(l.monthly_rent)} <span className="text-sm font-normal text-slate-500">· {fmtDate(l.start_date)} → {l.end_date ? fmtDate(l.end_date) : "∞"} · <Badge tone={l.status === "active" ? "green" : "slate"}>{l.status}</Badge></span></H1>
            <Balance id={id} />
            <Invoices id={id} canVoid={isOwner} />
            <Payments id={id} canReverse={isOwner} />
            <Ledger id={id} />
            <Tools id={id} hasTenant={!!l.tenant_id} ended={l.status !== "active"} />
            <Link href="/owner/properties" className="text-sm text-emerald-700 underline">← {t("back")}</Link>
          </>
        )}
      </QueryState>
    </div>
  );
}
