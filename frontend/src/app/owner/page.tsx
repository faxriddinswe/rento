"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { useT } from "@/i18n";
import { Card, H1, H2, QueryState, Table, Td } from "@/components/ui";

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <Card>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums sm:text-2xl ${tone}`}>{value}</p>
    </Card>
  );
}

export default function Dashboard() {
  const { t } = useT();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: async () => unwrap(await api.GET("/dashboard")) });
  return (
    <>
      <H1>{t("nav.dashboard")}</H1>
      <QueryState q={q}>
        {(d) => {
          const pct = d.expected > 0 ? Math.min(100, Math.round((d.collected / d.expected) * 100)) : 0;
          return (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label={t("dash.expected")} value={fmtMoney(d.expected)} />
                <Stat label={t("dash.collected")} value={fmtMoney(d.collected)} tone="text-emerald-600" />
                <Stat label={t("dash.outstanding")} value={fmtMoney(d.outstanding)} tone={d.outstanding ? "text-rose-600" : ""} />
                <Stat label={t("dash.activeLeases")} value={String(d.active_leases)} />
              </div>
              <Card>
                <div className="mb-1 flex justify-between text-sm"><span>{d.month}</span><span>{pct}%</span></div>
                <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
                </div>
              </Card>
              {d.pending_readings > 0 && (
                <Link href="/owner/readings" className="block rounded-2xl bg-amber-100 p-4 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                  📟 {t("dash.pendingReadings")}: <b>{d.pending_readings}</b>
                </Link>
              )}
              <Card>
                <H2>{t("dash.overdue")}</H2>
                {d.overdue.length === 0 ? <p className="text-slate-500">{t("dash.noOverdue")}</p> : (
                  <Table head={[t("dash.tenant"), t("dash.unit"), t("dash.oldestDue"), t("amount")]}>
                    {d.overdue.map((r) => (
                      <tr key={r.lease_id}>
                        <Td><Link className="text-emerald-700 underline" href={`/owner/leases/${r.lease_id}`}>{r.tenant_name ?? "—"}</Link></Td>
                        <Td>{r.property_name} / {r.unit_name}</Td>
                        <Td>{fmtDate(r.oldest_due_date)}</Td>
                        <Td right><span className="font-medium text-rose-600">{fmtMoney(r.overdue)}</span></Td>
                      </tr>
                    ))}
                  </Table>
                )}
              </Card>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
