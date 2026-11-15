"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, openPdf, unwrap } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { useMyLease } from "@/lib/tenant";
import { useAuth } from "@/lib/auth";
import { useT } from "@/i18n";
import { TelegramCard } from "@/components/telegram";
import { Badge, Button, Card, Empty, ErrorBox, H2, Loading, QueryState, Table, Td } from "@/components/ui";

function Content({ leaseId }: { leaseId: string }) {
  const { t } = useT();
  const bal = useQuery({ queryKey: ["balance", leaseId], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/balance", { params: { path: { lease_id: leaseId } } })) });
  const inv = useQuery({ queryKey: ["invoices", leaseId], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/invoices", { params: { path: { lease_id: leaseId } } })) });
  return (
    <div className="space-y-4">
      <QueryState q={bal}>
        {(b) => (
          <Card className={b.owed > 0 ? "border-rose-300" : "border-emerald-300"}>
            <p className="text-sm text-slate-500">{t("tenant.balanceTitle")}</p>
            {b.owed > 0 ? (
              <>
                <p className="mt-1 text-3xl font-bold tabular-nums text-rose-600">{fmtMoney(b.owed)}</p>
                <p className="text-sm text-slate-500">{t("tenant.toPay")}{b.overdue > 0 && <> · <Badge tone="red">{t("lease.overdue")}: {fmtMoney(b.overdue)}</Badge></>}</p>
                {b.next_due_date && <p className="mt-1 text-sm">{t("tenant.nextDue")}: <b>{fmtDate(b.next_due_date)}</b> ({fmtMoney(b.next_due_amount)})</p>}
              </>
            ) : b.credit > 0 ? (
              <p className="mt-1 text-3xl font-bold tabular-nums text-emerald-600">{fmtMoney(b.credit)} <span className="text-sm font-normal">{t("tenant.hasCredit")}</span></p>
            ) : <p className="mt-1 text-2xl font-semibold text-emerald-600">{t("tenant.allPaid")}</p>}
          </Card>
        )}
      </QueryState>
      <Link href="/tenant/readings/new" className="flex min-h-14 items-center justify-center rounded-2xl bg-emerald-600 px-4 text-lg font-semibold text-white">📷 {t("tenant.submitReading")}</Link>
      <Card>
        <H2>{t("tenant.currentInvoice")}</H2>
        <QueryState q={inv} isEmpty={(d) => d.length === 0}>
          {(rows) => {
            const i = rows[0];
            return (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span><b>{i.number}</b> · {fmtDate(i.period_start)}–{fmtDate(i.period_end)}</span>
                  <span className="text-lg font-semibold tabular-nums">{fmtMoney(i.total)}</span>
                </div>
                <Table head={[t("name"), t("amount")]}>
                  {i.lines.map((l) => <tr key={l.id}><Td>{l.pending_reading ? <i className="text-amber-700">{l.description}</i> : l.description}</Td><Td right>{fmtMoney(l.amount)}</Td></tr>)}
                </Table>
                <p className="mt-2 text-sm text-slate-500">{t("lease.due")}: {fmtDate(i.due_date)}</p>
                <Button variant="ghost" className="mt-2" onClick={() => void openPdf(`/invoices/${i.id}/pdf`)}>{t("download")}</Button>
              </div>
            );
          }}
        </QueryState>
      </Card>
      <TelegramCard />
    </div>
  );
}

export default function TenantHome() {
  const { me } = useAuth();
  const lease = useMyLease();
  const { t } = useT();
  if (lease.isLoading) return <Loading />;
  if (lease.isError) return <ErrorBox error={lease.error} retry={() => void lease.refetch()} />;
  if (!lease.data) return <Empty>{me?.full_name}: {t("empty")}</Empty>;
  return <Content leaseId={lease.data.id} />;
}
