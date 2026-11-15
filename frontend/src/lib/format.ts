/** Amounts come from the API as integer minor units (tiyin). */
export function fmtMoney(minor: number | null | undefined): string {
  const v = minor ?? 0;
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  const som = Math.floor(abs / 100);
  const tiyin = abs % 100;
  const s = som.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${s}${tiyin ? "." + String(tiyin).padStart(2, "0") : ""} so'm`;
}

/** "3000000" so'm typed by a human -> 300000000 tiyin (integer). */
export function somToMinor(input: string): number {
  const n = Number(input.replace(/\s/g, "").replace(",", "."));
  if (!Number.isFinite(n)) return NaN;
  return Math.round(n * 100);
}

export const fmtDate = (iso: string | null | undefined) => (iso ? iso.split("T")[0].split("-").reverse().join(".") : "—");
export const todayIso = () => new Date().toISOString().slice(0, 10);
