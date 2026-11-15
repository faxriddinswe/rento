"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api";
import { useT } from "@/i18n";
import { Button, Card, H1, QueryState, Table, Td } from "@/components/ui";

export default function Audit() {
  const { t } = useT();
  const [page, setPage] = useState(0);
  const q = useQuery({ queryKey: ["audit", page], queryFn: async () => unwrap(await api.GET("/audit", { params: { query: { limit: 50, offset: page * 50 } } })) });
  return (
    <>
      <H1>{t("audit.title")}</H1>
      <Card>
        <QueryState q={q} isEmpty={(d) => d.length === 0}>
          {(rows) => (
            <Table head={[t("audit.when"), t("audit.what"), t("audit.entity"), "before → after"]}>
              {rows.map((r) => (
                <tr key={r.id}>
                  <Td>{new Date(r.created_at).toLocaleString("uz-UZ")}</Td>
                  <Td><b>{r.action}</b></Td>
                  <Td>{r.entity_type}<br /><span className="text-xs text-slate-500">{r.entity_id.slice(0, 8)}</span></Td>
                  <Td><code className="text-xs break-all">{r.before ? JSON.stringify(r.before) + " → " : ""}{JSON.stringify(r.after)}</code></Td>
                </tr>
              ))}
            </Table>
          )}
        </QueryState>
        <div className="mt-3 flex gap-2">
          <Button variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>←</Button>
          <Button variant="ghost" disabled={(q.data?.length ?? 0) < 50} onClick={() => setPage(page + 1)}>→</Button>
        </div>
      </Card>
    </>
  );
}
