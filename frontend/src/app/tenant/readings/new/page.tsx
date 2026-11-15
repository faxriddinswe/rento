"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, errorMessage, unwrap, uploadToStorage } from "@/lib/api";
import { todayIso } from "@/lib/format";
import { useMyLease } from "@/lib/tenant";
import { useT } from "@/i18n";
import { Button, Card, Empty, Field, H1, Input, Loading, Select } from "@/components/ui";

export default function NewReading() {
  const { t } = useT();
  const qc = useQueryClient();
  const lease = useMyLease();
  const unitId = lease.data?.unit_id;
  const meters = useQuery({
    queryKey: ["meters", unitId],
    enabled: !!unitId,
    queryFn: async () => unwrap(await api.GET("/units/{unit_id}/meters", { params: { path: { unit_id: unitId! } } })),
  });
  const [meterId, setMeterId] = useState("");
  const [value, setValue] = useState("");
  const [date, setDate] = useState(todayIso());
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<"idle" | "uploading" | "sending" | "done">("idle");
  const [err, setErr] = useState("");

  if (lease.isLoading || meters.isLoading) return <Loading />;
  if (!lease.data || !meters.data?.length) return <Empty />;
  const active = meters.data.filter((m) => m.is_active);
  const selected = meterId || active[0]?.id || "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setErr("");
    try {
      setStage("uploading");
      const up = unwrap(await api.POST("/meters/{meter_id}/photo-upload", {
        params: { path: { meter_id: selected } },
        body: { content_type: file.type as "image/jpeg" | "image/png" | "image/webp", size: file.size },
      }));
      await uploadToStorage(up, file);
      setStage("sending");
      unwrap(await api.POST("/meters/{meter_id}/readings", { params: { path: { meter_id: selected } }, body: { value, reading_date: date, photo_key: up.key } }));
      setStage("done");
      setValue(""); setFile(null);
      void qc.invalidateQueries({ queryKey: ["tenant-readings"] });
    } catch (e) {
      setStage("idle");
      setErr(e instanceof ApiError && e.code === "reading_lower_than_previous" ? t("readings.lower") : errorMessage(e));
    }
  }

  return (
    <>
      <H1>{t("readings.submitTitle")}</H1>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("readings.meter")}>
            <Select value={selected} onChange={(e) => setMeterId(e.target.value)}>{active.map((m) => <option key={m.id} value={m.id}>{t(`kinds.${m.kind}`)} {m.serial}</option>)}</Select>
          </Field>
          <Field label={t("readings.value")}><Input inputMode="decimal" required pattern="[0-9]+([.,][0-9]{1,3})?" value={value} onChange={(e) => setValue(e.target.value.replace(",", "."))} className="text-2xl" /></Field>
          <Field label={t("date")}><Input type="date" required max={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label={t("readings.takePhoto")}>
            <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:min-h-11 file:rounded-xl file:border-0 file:bg-emerald-600 file:px-4 file:text-white" />
          </Field>
          {file && <p className="text-xs text-slate-500">{file.name} · {(file.size / 1024).toFixed(0)} KB</p>}
          {err && <p role="alert" className="text-sm text-rose-600">{err}</p>}
          {stage === "done" && <p role="status" className="text-sm font-medium text-emerald-600">{t("readings.sent")}</p>}
          <Button type="submit" className="w-full" disabled={stage === "uploading" || stage === "sending" || !file}>{stage === "uploading" ? t("readings.uploading") : t("readings.send")}</Button>
        </form>
      </Card>
    </>
  );
}
