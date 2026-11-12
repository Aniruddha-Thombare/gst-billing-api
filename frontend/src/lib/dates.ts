/** Date helpers in UTC, because the server works in UTC dates. */
export const iso = (d: Date) => d.toISOString().slice(0, 10);
export const monthStart = (ym: string) => `${ym}-01`;
export function firstDayMonthsAgo(months: number): string {
  const d = new Date();
  return iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - months, 1)));
}
/** Start of the current Indian financial year (1 April). */
export function financialYearStart(): string {
  const d = new Date();
  const year = d.getUTCMonth() >= 3 ? d.getUTCFullYear() : d.getUTCFullYear() - 1;
  return `${year}-04-01`;
}
