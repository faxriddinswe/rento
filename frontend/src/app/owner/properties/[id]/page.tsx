"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtMoney, somToMinor, todayIso } from "@/lib/format";
import { useT } from "@/i18n";
import { Badge, Button, Card, Field, H1, H2, Input, QueryState, Select, Table, Td } from "@/components/ui";

const KINDS = ["electricity", "water_cold", "water_hot", "gas", "heating", "other"] as const;
type Kind = (typeof KINDS)[number];
const PERMS = ["property.read", "unit.manage", "lease.read", "lease.manage", "meter.read", "meter.manage", "tariff.read", "tariff.manage", "reading.read", "reading.review", "invoice.read", "payment.read", "payment.record", "ledger.read", "document.read", "document.generate", "dashboard.read"];

function Err({ e }: { e: unknown }) {
  return e ? <p role="alert" className="text-sm text-rose-600">{errorMessage(e)}</p> : null;
}

function MeterRow({ meter }: { meter: { id: string; kind: string; serial: string; unit_label: string } }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ value: "", date: todayIso(), old: "" });
  const m = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/meters/{meter_id}/baseline", {
        params: { path: { meter_id: meter.id } },
        body: { value: f.value, reading_date: f.date, replaced_final_value: f.old || null },
      })),
    onSuccess: () => { setOpen(false); setF({ value: "", date: todayIso(), old: "" }); void qc.invalidateQueries({ queryKey: ["readings"] }); },
  });
  return (
    <li className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800">
      <div className="flex items-center justify-between gap-2">
        <span>{t(`kinds.${meter.kind}`)} <span className="text-slate-500">{meter.serial}</span></span>
        <Button variant="ghost" onClick={() => setOpen(!open)}>{t("prop.baseline")}</Button>
      </div>
      {open && (
        <form className="mt-3 space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <Field label={t("prop.baselineValue")}><Input required inputMode="decimal" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></Field>
          <Field label={t("date")}><Input type="date" required value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label={t("prop.oldFinal")}><Input inputMode="decimal" value={f.old} onChange={(e) => setF({ ...f, old: e.target.value })} /></Field>
          <Err e={m.error} />
          <Button type="submit" disabled={m.isPending}>{t("save")}</Button>
        </form>
      )}
    </li>
  );
}

function UnitCard({ unit }: { unit: { id: string; name: string } }) {
  const { t } = useT();
  const qc = useQueryClient();
  const meters = useQuery({ queryKey: ["meters", unit.id], queryFn: async () => unwrap(await api.GET("/units/{unit_id}/meters", { params: { path: { unit_id: unit.id } } })) });
  const leases = useQuery({ queryKey: ["leases", { unit: unit.id }], queryFn: async () => unwrap(await api.GET("/leases", { params: { query: { unit_id: unit.id } } })) });
  const [kind, setKind] = useState<Kind>("electricity");
  const [serial, setSerial] = useState("");
  const [label, setLabel] = useState("kWh");
  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/units/{unit_id}/meters", { params: { path: { unit_id: unit.id } }, body: { kind, serial, unit_label: label } })),
    onSuccess: () => { setSerial(""); void qc.invalidateQueries({ queryKey: ["meters", unit.id] }); },
  });
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">{unit.name}</h3>
        <Link href={`/owner/leases/new?unit=${unit.id}`} className="rounded-xl bg-emerald-600 px-3 py-2 text-sm text-white">{t("prop.newLease")}</Link>
      </div>
      <QueryState q={leases}>
        {(ls) => ls.length === 0 ? <p className="mb-3 text-sm text-slate-500">{t("prop.noLease")}</p> : (
          <ul className="mb-3 space-y-1 text-sm">
            {ls.map((l) => (
              <li key={l.id}><Link className="text-emerald-700 underline" href={`/owner/leases/${l.id}`}>{fmtDate(l.start_date)} → {l.end_date ? fmtDate(l.end_date) : "∞"}</Link> · {fmtMoney(l.monthly_rent)} <Badge tone={l.status === "active" ? "green" : "slate"}>{l.status}</Badge></li>
            ))}
          </ul>
        )}
      </QueryState>
      <h4 className="mb-2 text-sm font-medium text-slate-500">{t("prop.meters")}</h4>
      <QueryState q={meters} isEmpty={() => false}>{(ms) => <ul className="mb-3 space-y-2">{ms.map((m) => <MeterRow key={m.id} meter={m} />)}</ul>}</QueryState>
      <form className="grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <Select value={kind} onChange={(e) => setKind(e.target.value as Kind)} aria-label={t("prop.kind")}>{KINDS.map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select>
        <Input placeholder={t("prop.serial")} value={serial} onChange={(e) => setSerial(e.target.value)} />
        <Input placeholder="kWh / m³" value={label} onChange={(e) => setLabel(e.target.value)} />
        <Button type="submit" disabled={add.isPending}>{t("prop.newMeter")}</Button>
      </form>
      <Err e={add.error} />
    </Card>
  );
}

function parseTiers(text: string) {
  const rows = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (rows.length === 0) return null;
  return rows.map((r) => {
    const [upTo, price] = r.split(":").map((s) => s.trim());
    return { up_to: upTo === "*" ? null : upTo, price: String(somToMinor(price)) };
  });
}

function Tariffs({ propertyId }: { propertyId: string }) {
  const { t } = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tariffs", propertyId], queryFn: async () => unwrap(await api.GET("/properties/{property_id}/tariffs", { params: { path: { property_id: propertyId } } })) });
  const [f, setF] = useState({ kind: "electricity" as Kind, from: todayIso(), price: "", tiers: "" });
  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/properties/{property_id}/tariffs", {
      params: { path: { property_id: propertyId } },
      body: { kind: f.kind, name: "", effective_from: f.from, unit_price: String(somToMinor(f.price || "0")), tiers: parseTiers(f.tiers) },
    })),
    onSuccess: () => { setF({ ...f, price: "", tiers: "" }); void qc.invalidateQueries({ queryKey: ["tariffs", propertyId] }); },
  });
  return (
    <section>
      <H2>{t("prop.tariffs")}</H2>
      <Card>
        <QueryState q={q}>
          {(rows) => (
            <Table head={[t("prop.kind"), t("prop.effectiveFrom"), t("prop.effectiveTo"), t("prop.unitPrice")]}>
              {rows.map((r) => (
                <tr key={r.id}>
                  <Td>{t(`kinds.${r.kind}`)}</Td><Td>{fmtDate(r.effective_from)}</Td><Td>{r.effective_to ? fmtDate(r.effective_to) : <Badge tone="green">hozir</Badge>}</Td>
                  <Td right>{r.tiers ? r.tiers.map((x) => `${x.up_to ?? "∞"}: ${fmtMoney(Number(x.price))}`).join(" | ") : fmtMoney(Number(r.unit_price))}</Td>
                </tr>
              ))}
            </Table>
          )}
        </QueryState>
        <form className="mt-4 grid gap-3 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Field label={t("prop.kind")}><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Kind })}>{KINDS.map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select></Field>
          <Field label={t("prop.effectiveFrom")}><Input type="date" required value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></Field>
          <Field label={t("prop.unitPrice")}><Input inputMode="decimal" required={!f.tiers} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></Field>
          <div className="flex items-end"><Button type="submit" disabled={add.isPending} className="w-full">{t("prop.newTariff")}</Button></div>
          <div className="sm:col-span-4">
            <Field label="Bosqichli tarif (ixtiyoriy): har qatorda «gacha: narx», oxirgisi «*: narx»"><textarea className="min-h-16 w-full rounded-xl border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-950" value={f.tiers} onChange={(e) => setF({ ...f, tiers: e.target.value })} placeholder={"100: 1000\n*: 1500"} /></Field>
          </div>
        </form>
        <Err e={add.error} />
      </Card>
    </section>
  );
}

function Managers({ propertyId }: { propertyId: string }) {
  const { t } = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["managers", propertyId], queryFn: async () => unwrap(await api.GET("/properties/{property_id}/managers", { params: { path: { property_id: propertyId } } })) });
  const [f, setF] = useState({ email: "", full_name: "", password: "", perms: ["property.read", "lease.read", "reading.read", "reading.review"] as string[] });
  const add = useMutation({
    mutationFn: async () => unwrap(await api.PUT("/properties/{property_id}/managers", { params: { path: { property_id: propertyId } }, body: { email: f.email, full_name: f.full_name, password: f.password || null, permissions: f.perms } })),
    onSuccess: () => { setF({ ...f, email: "", full_name: "", password: "" }); void qc.invalidateQueries({ queryKey: ["managers", propertyId] }); },
  });
  const remove = useMutation({
    mutationFn: async (user_id: string) => { await api.DELETE("/properties/{property_id}/managers/{user_id}", { params: { path: { property_id: propertyId, user_id } } }); },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["managers", propertyId] }),
  });
  return (
    <section>
      <H2>{t("prop.managers")}</H2>
      <Card>
        <QueryState q={q}>
          {(rows) => (
            <ul className="mb-4 space-y-2 text-sm">
              {rows.map((m) => (
                <li key={m.user_id} className="flex items-start justify-between gap-2">
                  <span><b>{m.full_name}</b> · {m.email}<br /><span className="text-xs text-slate-500">{m.permissions.join(", ")}</span></span>
                  <Button variant="ghost" onClick={() => remove.mutate(m.user_id)}>×</Button>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t("email")}><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label={t("fullName")}><Input required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label={t("password")}><Input type="password" minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          </div>
          <fieldset><legend className="mb-1 text-sm text-slate-600">{t("prop.permissions")}</legend>
            <div className="grid grid-cols-2 gap-1 text-sm sm:grid-cols-3">
              {PERMS.map((p) => (
                <label key={p} className="flex items-center gap-2"><input type="checkbox" checked={f.perms.includes(p)} onChange={(e) => setF({ ...f, perms: e.target.checked ? [...f.perms, p] : f.perms.filter((x) => x !== p) })} />{p}</label>
              ))}
            </div>
          </fieldset>
          <Err e={add.error} />
          <Button type="submit" disabled={add.isPending}>{t("prop.addManager")}</Button>
        </form>
      </Card>
    </section>
  );
}

export default function PropertyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { t } = useT();
  const { me } = useAuth();
  const qc = useQueryClient();
  const prop = useQuery({ queryKey: ["property", id], queryFn: async () => unwrap(await api.GET("/properties/{property_id}", { params: { path: { property_id: id } } })) });
  const units = useQuery({ queryKey: ["units", id], queryFn: async () => unwrap(await api.GET("/properties/{property_id}/units", { params: { path: { property_id: id } } })) });
  const [uname, setUname] = useState("");
  const addUnit = useMutation({
    mutationFn: async () => unwrap(await api.POST("/properties/{property_id}/units", { params: { path: { property_id: id } }, body: { name: uname } })),
    onSuccess: () => { setUname(""); void qc.invalidateQueries({ queryKey: ["units", id] }); },
  });
  return (
    <div className="space-y-6">
      <QueryState q={prop}>{(p) => <H1>{p.name}<span className="ml-2 text-sm font-normal text-slate-500">{p.address}</span></H1>}</QueryState>
      <section>
        <H2>{t("prop.units")}</H2>
        <QueryState q={units}>{(us) => <div className="space-y-3">{us.map((u) => <UnitCard key={u.id} unit={u} />)}</div>}</QueryState>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); addUnit.mutate(); }}>
          <Input required placeholder={t("prop.newUnit")} value={uname} onChange={(e) => setUname(e.target.value)} />
          <Button type="submit" disabled={addUnit.isPending}>{t("add")}</Button>
        </form>
        <Err e={addUnit.error} />
      </section>
      <Tariffs propertyId={id} />
      {me?.role === "owner" && <Managers propertyId={id} />}
    </div>
  );
}
