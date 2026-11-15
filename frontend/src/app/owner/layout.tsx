"use client";

import type { ReactNode } from "react";
import { Shell } from "@/components/shell";
import { useT } from "@/i18n";
import { useAuth } from "@/lib/auth";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  const { t } = useT();
  const { me } = useAuth();
  const nav = [
    { href: "/owner", label: t("nav.dashboard") },
    { href: "/owner/properties", label: t("nav.properties") },
    { href: "/owner/readings", label: t("nav.readings") },
    ...(me?.role === "owner" ? [{ href: "/owner/settings", label: t("nav.settings") }, { href: "/owner/audit", label: t("nav.audit") }] : []),
  ];
  return <Shell area="owner" nav={nav}>{children}</Shell>;
}
