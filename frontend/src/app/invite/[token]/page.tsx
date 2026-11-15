"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { Button, Card, Field, H1, Input, QueryState } from "@/components/ui";

export default function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const { t } = useT();
  const { signIn } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ["invite", token], queryFn: async () => unwrap(await api.GET("/auth/invite/{token}", { params: { path: { token } } })), retry: false });

  async function accept(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const tok = unwrap(await api.POST("/auth/invite/accept", { body: { token, password } }));
      await signIn(tok);
      router.replace("/tenant");
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md px-4 py-10">
      <H1>{t("auth.inviteTitle")}</H1>
      <QueryState q={q}>
        {(inv) => (
          <Card>
            <p className="mb-1 text-sm text-slate-600 dark:text-slate-400">{t("auth.inviteIntro")}</p>
            <p className="mb-4 text-lg font-semibold">{inv.unit_name}</p>
            <p className="mb-4 text-sm">{inv.full_name} · {inv.email}</p>
            <form onSubmit={accept} className="space-y-4">
              <Field label={t("auth.setPassword")}><Input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
              {err && <p role="alert" className="text-sm text-rose-600">{err}</p>}
              <Button type="submit" disabled={busy} className="w-full">{t("auth.accept")}</Button>
            </form>
          </Card>
        )}
      </QueryState>
    </main>
  );
}
