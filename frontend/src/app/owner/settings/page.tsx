"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useT } from "@/i18n";
import { Button, Card, H1, H2, QueryState } from "@/components/ui";
import { TelegramCard } from "@/components/telegram";


export default function Settings() {
  const { t } = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["template"], queryFn: async () => unwrap(await api.GET("/settings/contract-template")) });
  const [body, setBody] = useState("");
  useEffect(() => { if (q.data) setBody(q.data.body); }, [q.data]);
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PUT("/settings/contract-template", { body: { body } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["template"] }),
  });
  return (
    <div className="space-y-6">
      <H1>{t("nav.settings")}</H1>
      <Card>
        <H2>{t("settings.template")}</H2>
        <QueryState q={q}>
          {(tpl) => (
            <>
              <p className="mb-2 text-sm text-slate-500">{t("settings.version")}: {tpl.version} · {t("settings.placeholders")}: {tpl.placeholders.map((p) => `{{ ${p} }}`).join("  ")}</p>
              <textarea className="min-h-80 w-full rounded-xl border border-slate-300 p-3 font-mono text-sm dark:border-slate-700 dark:bg-slate-950" value={body} onChange={(e) => setBody(e.target.value)} />
              <p className="my-2 text-xs text-slate-500">{t("settings.disclaimer")}</p>
              {save.isError && <p role="alert" className="text-sm text-rose-600">{errorMessage(save.error)}</p>}
              {save.isSuccess && <p className="text-sm text-emerald-600">{t("settings.saved")}</p>}
              <Button onClick={() => save.mutate()} disabled={save.isPending}>{t("save")}</Button>
            </>
          )}
        </QueryState>
      </Card>
      <TelegramCard />
    </div>
  );
}
