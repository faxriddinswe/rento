"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { Button, Card, Field, H1, Input } from "@/components/ui";

export default function SignupPage() {
  const { t } = useT();
  const { signIn } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ full_name: "", email: "", password: "", phone: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const tok = unwrap(await api.POST("/auth/signup", { body: { ...f, phone: f.phone || null } }));
      await signIn(tok);
      router.replace("/owner");
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-md px-4 py-10">
      <H1>{t("auth.signupTitle")}</H1>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("fullName")}><Input required value={f.full_name} onChange={set("full_name")} /></Field>
          <Field label={t("email")}><Input type="email" required value={f.email} onChange={set("email")} /></Field>
          <Field label={t("phone")}><Input type="tel" value={f.phone} onChange={set("phone")} /></Field>
          <Field label={t("password")}><Input type="password" required minLength={8} value={f.password} onChange={set("password")} /></Field>
          {err && <p role="alert" className="text-sm text-rose-600">{err}</p>}
          <Button type="submit" disabled={busy} className="w-full">{t("signup")}</Button>
        </form>
      </Card>
      <p className="mt-4 text-center text-sm">{t("auth.haveAccount")} <Link className="text-emerald-700 underline" href="/login">{t("login")}</Link></p>
    </main>
  );
}
