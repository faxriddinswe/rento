import createClient from "openapi-fetch";
import type { paths } from "./api-types";

const BASE = "/api";
const KEY = "rento.tokens";

export type Tokens = { access_token: string; refresh_token: string };

export function getTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}
export function setTokens(t: Tokens | null) {
  try {
    if (t) localStorage.setItem(KEY, JSON.stringify(t));
    else localStorage.removeItem(KEY);
  } catch {}
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const t = getTokens();
  if (!t) return false;
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: t.refresh_token }),
      });
      if (!r.ok) {
        setTokens(null);
        return false;
      }
      setTokens((await r.json()) as Tokens);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

/** fetch with bearer token; on 401 refreshes once (rotating refresh token) and retries. */
const authFetch = async (request: Request): Promise<Response> => {
  const retry = request.clone();
  const t = getTokens();
  if (t) request.headers.set("authorization", `Bearer ${t.access_token}`);
  const res = await fetch(request);
  if (res.status === 401 && t && !request.url.includes("/auth/")) {
    if (await refreshTokens()) {
      const fresh = getTokens();
      if (fresh) retry.headers.set("authorization", `Bearer ${fresh.access_token}`);
      return fetch(retry);
    }
    if (typeof window !== "undefined") window.dispatchEvent(new Event("rento:logout"));
  }
  return res;
};

export const api = createClient<paths>({ baseUrl: BASE, fetch: authFetch });

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Turn an openapi-fetch result into data or a thrown ApiError carrying the server's message. */
export function unwrap<T>(res: Result<T>): T {
  if (res.error !== undefined || !res.response.ok) {
    const e = (res.error ?? {}) as { error?: { code?: string; message?: string } };
    throw new ApiError(res.response.status, e.error?.code ?? "error", e.error?.message ?? res.response.statusText);
  }
  return res.data as T;
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Download an authenticated binary (PDF) and open it. */
export async function openPdf(path: string) {
  const t = getTokens();
  const r = await fetch(`${BASE}${path}`, { headers: t ? { authorization: `Bearer ${t.access_token}` } : {} });
  if (!r.ok) throw new ApiError(r.status, "download", "PDF yuklab bo'lmadi");
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Step 2 of the photo flow: browser -> object storage directly with the presigned POST. */
export async function uploadToStorage(post: { url: string; fields: Record<string, string> }, file: File) {
  const form = new FormData();
  Object.entries(post.fields).forEach(([k, v]) => form.append(k, v));
  form.append("file", file); // must be last
  const r = await fetch(post.url, { method: "POST", body: form });
  if (!r.ok) throw new ApiError(r.status, "upload", "Rasm yuklanmadi");
}
