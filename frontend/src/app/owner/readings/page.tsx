"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useT } from "@/i18n";
import { Badge, Button, Card, H1, Input, QueryState } from "@/components/ui";

type Reading = { id: string; meter_id: string; value: string | number; reading_date: string; photo_url?: string | null; status: string; reject_reason?: string | null };

function Item({ r }: { r: Reading }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [oldFinal, setOldFinal] = useState("");
  const [replacing, setReplacing] = useState(false);
  const done = () => { void qc.invalidateQueries({ queryKey: ["readings"] }); void qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const confirm = useMutation({
    mutationFn: async (replaced: boolean) => unwrap(await api.POST("/readings/{reading_id}/confirm", { params: { path: { reading_id: r.id } }, body: { meter_replaced: replaced, replaced_final_value: replaced && oldFinal ? oldFinal : null } })),
    onSuccess: done,
  });
  const reject = useMutation({
    mutationFn: async () => unwrap(await api.POST("/readings/{reading_id}/reject", { params: { path: { reading_id: r.id } }, body: { reason } })),
    onSuccess: done,
  });
  const err = confirm.error ?? reject.error;
  return (
    <Card>
      <div className="flex flex-col gap-3 sm:flex-row">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {r.photo_url ? <a href={r.photo_url} target="_blank" rel="noreferrer"><img src={r.photo_url} alt={t("readings.photo")} className="h-40 w-full rounded-xl object-cover sm:w-52" /></a> : <div className="flex h-40 w-full items-center justify-center rounded-xl bg-slate-100 text-sm text-slate-400 sm:w-52 dark:bg-slate-800">—</div>}
        <div className="flex-1">
          <p className="text-3xl font-semibold tabular-nums">{String(r.value)}</p>
          <p className="text-sm text-slate-500">{fmtDate(r.reading_date)} · <Badge tone="amber">{t(`readings.statuses.${r.status}`)}</Badge></p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button disabled={confirm.isPending} onClick={() => confirm.mutate(false)}>{t("readings.confirm")}</Button>
            <Button variant="ghost" onClick={() => setReplacing(!replacing)}>{t("readings.confirmReplaced")}</Button>
            <Button variant="danger" onClick={() => setRejecting(!rejecting)}>{t("readings.reject")}</Button>
          </div>
          {replacing && (
            <div className="mt-3 flex gap-2"><Input inputMode="decimal" placeholder={t("prop.oldFinal")} value={oldFinal} onChange={(e) => setOldFinal(e.target.value)} /><Button onClick={() => confirm.mutate(true)}>OK</Button></div>
          )}
          {rejecting && (
            <div className="mt-3 flex gap-2"><Input placeholder={t("readings.rejectReason")} value={reason} onChange={(e) => setReason(e.target.value)} /><Button variant="danger" disabled={!reason || reject.isPending} onClick={() => reject.mutate()}>OK</Button></div>
          )}
          {err && <p role="alert" className="mt-2 text-sm text-rose-600">{errorMessage(err)}</p>}
        </div>
      </div>
    </Card>
  );
}

export default function Readings() {
  const { t } = useT();
  const q = useQuery({ queryKey: ["readings", "pending"], queryFn: async () => unwrap(await api.GET("/readings", { params: { query: { status: "pending" } } })) });
  return (
    <>
      <H1>{t("readings.inbox")}</H1>
      <QueryState q={q} isEmpty={(d) => d.length === 0}>
        {(rows) => <div className="space-y-3">{rows.map((r) => <Item key={r.id} r={r} />)}</div>}
      </QueryState>
    </>
  );
}
