"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { Button, Card, Field, H1, Input } from "@/components/ui";

export default function LoginPage() {
  const { t } = useT();
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const tok = unwrap(await api.POST("/auth/login", { body: { email, password } }));
      const me = await signIn(tok);
      router.replace(me.role === "tenant" ? "/tenant" : "/owner");
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md px-4 py-10">
      <H1>{t("auth.loginTitle")}</H1>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("email")}><Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label={t("password")}><Input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          {err && <p role="alert" className="text-sm text-rose-600">{err}</p>}
          <Button type="submit" disabled={busy} className="w-full">{t("login")}</Button>
        </form>
      </Card>
      <p className="mt-4 text-center text-sm">{t("auth.noAccount")} <Link className="text-emerald-700 underline" href="/signup">{t("signup")}</Link></p>
    </main>
  );
}
