"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useT } from "@/i18n";
import { Button, Card, H2 } from "@/components/ui";

export function TelegramCard() {
  const { t } = useT();
  const me = useQuery({ queryKey: ["me"], queryFn: async () => unwrap(await api.GET("/auth/me")) });
  const link = useMutation({ mutationFn: async () => unwrap(await api.POST("/auth/telegram-link")) });
  return (
    <Card>
      <H2>{t("tenant.telegram")}</H2>
      {me.data?.telegram_linked ? <p>{t("tenant.telegramLinked")}</p> : (
        <>
          <Button onClick={() => link.mutate()} disabled={link.isPending}>{t("tenant.linkTelegram")}</Button>
          {link.data && (link.data.url ? <a className="ml-3 text-emerald-700 underline" href={link.data.url} target="_blank" rel="noreferrer">{link.data.url}</a> : <p className="mt-2 text-sm text-amber-700">{t("tenant.telegramOff")}</p>)}
          {link.isError && <p role="alert" className="text-sm text-rose-600">{errorMessage(link.error)}</p>}
        </>
      )}
    </Card>
  );
}
