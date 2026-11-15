"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { Button, Card, Field, H1, H2, Input, QueryState } from "@/components/ui";

export default function Properties() {
  const { t } = useT();
  const { me } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["properties"], queryFn: async () => unwrap(await api.GET("/properties")) });
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/properties", { body: { name, address } })),
    onSuccess: () => { setName(""); setAddress(""); void qc.invalidateQueries({ queryKey: ["properties"] }); },
  });
  return (
    <>
      <H1>{t("prop.title")}</H1>
      <QueryState q={q} isEmpty={(d) => d.length === 0 && me?.role !== "owner"}>
        {(list) => (
          <div className="grid gap-3 sm:grid-cols-2">
            {list.map((p) => (
              <Link key={p.id} href={`/owner/properties/${p.id}`}>
                <Card className="transition hover:border-emerald-400"><p className="font-semibold">{p.name}</p><p className="text-sm text-slate-500">{p.address || "—"}</p></Card>
              </Link>
            ))}
          </div>
        )}
      </QueryState>
      {me?.role === "owner" && (
        <Card className="mt-6">
          <H2>{t("prop.new")}</H2>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Field label={t("name")}><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label={t("address")}><Input value={address} onChange={(e) => setAddress(e.target.value)} /></Field>
            {create.isError && <p role="alert" className="text-sm text-rose-600">{errorMessage(create.error)}</p>}
            <Button type="submit" disabled={create.isPending}>{t("create")}</Button>
          </form>
        </Card>
      )}
    </>
  );
}
