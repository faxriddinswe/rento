"use client";

import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./api";

/** The signed-in tenant's current lease (active one first). */
export function useMyLease() {
  return useQuery({
    queryKey: ["my-lease"],
    queryFn: async () => {
      const leases = unwrap(await api.GET("/leases"));
      return leases.find((l) => l.status === "active") ?? leases[0] ?? null;
    },
  });
}
