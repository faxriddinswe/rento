"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api, getTokens, setTokens, unwrap, type Tokens } from "./api";
import type { components } from "./api-types";

export type Me = components["schemas"]["UserOut"];
type AuthCtx = {
  me: Me | null;
  loading: boolean;
  signIn: (t: Tokens) => Promise<Me>;
  signOut: () => void;
};
const Ctx = createContext<AuthCtx>({ me: null, loading: true, signIn: async () => { throw new Error("no provider"); }, signOut: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();
  const router = useRouter();

  const load = useCallback(async () => {
    if (!getTokens()) {
      setMe(null);
      setLoading(false);
      return null;
    }
    try {
      const u = unwrap(await api.GET("/auth/me"));
      setMe(u);
      return u;
    } catch {
      setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const signOut = useCallback(() => {
    const t = getTokens();
    if (t) void api.POST("/auth/logout", { body: { refresh_token: t.refresh_token } });
    setTokens(null);
    setMe(null);
    qc.clear();
    router.push("/login");
  }, [qc, router]);

  useEffect(() => {
    const h = () => {
      setTokens(null);
      setMe(null);
      qc.clear();
      router.push("/login");
    };
    window.addEventListener("rento:logout", h);
    return () => window.removeEventListener("rento:logout", h);
  }, [qc, router]);

  const signIn = useCallback(
    async (t: Tokens) => {
      setTokens(t);
      qc.clear();
      const u = unwrap(await api.GET("/auth/me"));
      setMe(u);
      return u;
    },
    [qc],
  );

  return <Ctx.Provider value={{ me, loading, signIn, signOut }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
