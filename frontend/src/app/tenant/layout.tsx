"use client";

import type { ReactNode } from "react";
import { Shell } from "@/components/shell";
import { useT } from "@/i18n";

export default function TenantLayout({ children }: { children: ReactNode }) {
  const { t } = useT();
  return (
    <Shell area="tenant" nav={[
      { href: "/tenant", label: t("nav.home") },
      { href: "/tenant/readings/new", label: t("nav.submit") },
      { href: "/tenant/history", label: t("nav.history") },
    ]}>{children}</Shell>
  );
}
