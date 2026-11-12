/** "1234567.5" -> "12,34,567.50". Works on STRINGS: money is never turned into a float. */
export function formatINR(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const [wholeRaw, fracRaw = ""] = String(value).split(".");
  const negative = wholeRaw.startsWith("-");
  const whole = wholeRaw.replace("-", "");
  const frac = (fracRaw + "00").slice(0, 2);
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3);
  const grouped = rest ? `${rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${last3}` : last3;
  return `${negative ? "-" : ""}${grouped}.${frac}`;
}

export const rupees = (value: string | null | undefined) => `₹${formatINR(value)}`;

/** Short form for chart axes: 1250000 -> "12.5L". Display only, never used for calculation. */
export function compactINR(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${(value / 1e7).toFixed(1)}Cr`;
  if (abs >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return String(value);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d} ${months[Number(m) - 1]} ${y}`;
}

/** Today's date as YYYY-MM-DD in UTC. The backend uses UTC, and rejects future-dated invoices. */
export const todayUtc = () => new Date().toISOString().slice(0, 10);
