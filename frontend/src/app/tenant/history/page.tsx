"use client";

import { useQuery } from "@tanstack/react-query";
import { api, openPdf, unwrap } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { useMyLease } from "@/lib/tenant";
import { useT } from "@/i18n";
import { Badge, Button, Card, Empty, ErrorBox, H1, H2, Loading, QueryState, Table, Td } from "@/components/ui";

function History({ leaseId }: { leaseId: string }) {
  const { t } = useT();
  const inv = useQuery({ queryKey: ["invoices", leaseId], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/invoices", { params: { path: { lease_id: leaseId } } })) });
  const pays = useQuery({ queryKey: ["payments", leaseId], queryFn: async () => unwrap(await api.GET("/leases/{lease_id}/payments", { params: { path: { lease_id: leaseId } } })) });
  const reads = useQuery({ queryKey: ["tenant-readings"], queryFn: async () => unwrap(await api.GET("/readings")) });
  const tone = (s: string) => (s === "confirmed" ? "green" : s === "rejected" ? "red" : "amber");
  return (
    <div className="space-y-4">
      <Card><H2>{t("lease.invoices")}</H2>
        <QueryState q={inv} isEmpty={(d) => d.length === 0}>
          {(rows) => (
            <Table head={[t("lease.period"), t("total"), t("status"), ""]}>
              {rows.map((i) => (
                <tr key={i.id}><Td>{fmtDate(i.period_start)}</Td><Td right>{fmtMoney(i.total)}</Td>
                  <Td>{i.status === "void" ? <Badge tone="red">{t("lease.void2")}</Badge> : i.remaining === 0 ? <Badge tone="green">{t("lease.paid")}</Badge> : <Badge tone="amber">{fmtMoney(i.remaining)}</Badge>}</Td>
                  <Td><Button variant="ghost" onClick={() => void openPdf(`/invoices/${i.id}/pdf`)}>PDF</Button></Td></tr>
              ))}
            </Table>
          )}
        </QueryState>
      </Card>
      <Card><H2>{t("lease.payments")}</H2>
        <QueryState q={pays} isEmpty={(d) => d.length === 0}>
          {(rows) => (
            <Table head={[t("date"), t("amount"), t("lease.method")]}>
              {rows.filter((p) => !p.reversed_at).map((p) => <tr key={p.id}><Td>{fmtDate(p.paid_on)}</Td><Td right>{fmtMoney(p.amount)}</Td><Td>{t(`lease.methods.${p.method}`)}</Td></tr>)}
            </Table>
          )}
        </QueryState>
      </Card>
      <Card><H2>{t("readings.mine")}</H2>
        <QueryState q={reads} isEmpty={(d) => d.length === 0}>
          {(rows) => (
            <ul className="space-y-2 text-sm">
              {rows.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{fmtDate(r.reading_date)} · <b className="tabular-nums">{String(r.value)}</b></span>
                  <span><Badge tone={tone(r.status)}>{t(`readings.statuses.${r.status}`)}</Badge>{r.reject_reason && <span className="ml-2 text-rose-600">{r.reject_reason}</span>}</span>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </Card>
    </div>
  );
}

export default function TenantHistory() {
  const { t } = useT();
  const lease = useMyLease();
  if (lease.isLoading) return <Loading />;
  if (lease.isError) return <ErrorBox error={lease.error} retry={() => void lease.refetch()} />;
  if (!lease.data) return <Empty />;
  return (<><H1>{t("tenant.history")}</H1><History leaseId={lease.data.id} /></>);
}
