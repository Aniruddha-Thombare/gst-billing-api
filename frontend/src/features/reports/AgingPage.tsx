import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART, compactNumber } from "@/components/common/ChartTheme";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { usePagedList } from "@/hooks/usePagedList";
import { http } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";

interface Buckets { current: string; days_1_30: string; days_31_60: string; days_61_90: string; over_90: string; total: string; invoice_count: number; }
interface Summary { as_of_date: string; buckets: Buckets; refund_due_total: string; refund_due_invoice_count: number; }
interface PartyRow extends Buckets { party_id: string; party_name: string; oldest_due_date: string; }
const LABELS: [keyof Buckets, string, string][] = [["current", "Not yet due", CHART.teal], ["days_1_30", "1-30 days", CHART.sky], ["days_31_60", "31-60 days", CHART.amber], ["days_61_90", "61-90 days", "#fb923c"], ["over_90", "Over 90 days", CHART.rose]];

export function AgingPage() {
  const [asOf, setAsOf] = useState("");
  const summary = useQuery({ queryKey: ["aging", asOf], queryFn: async () => (await http.get<Summary>("/reports/ar-aging", { params: asOf ? { as_of_date: asOf } : {} })).data });
  const parties = usePagedList<PartyRow>("aging-parties", "/reports/ar-aging/parties", { as_of_date: asOf });
  const b = summary.data?.buckets;
  const chart = b ? LABELS.map(([k, name, color]) => ({ name, value: Number(b[k]), color })) : [];
  return (
    <div className="space-y-6">
      <PageHeader title="Receivables Aging" subtitle="How late the money owed to you is" />
      <label className="flex items-center gap-2 text-sm text-muted-foreground">As of<Input type="date" className="w-44" value={asOf} onChange={(e) => setAsOf(e.target.value)} /><span>(empty = today)</span></label>
      {summary.isError ? <p role="alert" className="text-destructive">{errorMessage(summary.error)}</p> : null}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardContent className="h-64 pt-6">
          {summary.isLoading ? <Skeleton className="h-full w-full" /> : (
            <ResponsiveContainer width="100%" height="100%"><BarChart data={chart}>
              <CartesianGrid stroke={CHART.grid} strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis tickFormatter={compactNumber} width={48} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>{chart.map((c) => <Cell key={c.name} fill={c.color} />)}</Bar>
            </BarChart></ResponsiveContainer>)}
        </CardContent></Card>
        <Card><CardContent className="space-y-2 pt-6 text-sm">
          <div className="text-xs text-muted-foreground">Total receivable</div>
          <div className="text-2xl font-bold tabular-nums">{b ? rupees(b.total) : "—"}</div>
          <div className="text-muted-foreground">{b?.invoice_count ?? 0} open invoices</div>
          {summary.data && Number(summary.data.refund_due_total) > 0 ? <div className="border-t pt-2">Refunds owed to customers (separate, not netted): <b>{rupees(summary.data.refund_due_total)}</b> on {summary.data.refund_due_invoice_count} invoice(s)</div> : null}
        </CardContent></Card>
      </div>
      <Card className="overflow-x-auto"><Table>
        <THead><TR><TH>Customer</TH><TH>Oldest due</TH>{LABELS.map(([, n]) => <TH key={n} className="text-right">{n}</TH>)}<TH className="text-right">Total</TH></TR></THead>
        <TBody>
          {parties.isLoading ? <TR><TD colSpan={8}><Skeleton className="h-5 w-full" /></TD></TR> : null}
          {!parties.isLoading && parties.rows.length === 0 ? <TR><TD colSpan={8} className="py-8 text-center text-muted-foreground">Nothing outstanding.</TD></TR> : null}
          {parties.rows.map((r) => (
            <TR key={r.party_id}><TD className="font-medium">{r.party_name}</TD><TD>{fmtDate(r.oldest_due_date)}</TD>
              {LABELS.map(([k]) => <TD key={k} className="text-right tabular-nums">{Number(r[k]) === 0 ? "—" : rupees(r[k] as string)}</TD>)}
              <TD className="text-right font-medium tabular-nums">{rupees(r.total)}</TD></TR>))}
        </TBody>
      </Table></Card>
      {parties.hasNextPage ? <div className="text-center"><Button variant="outline" disabled={parties.isFetchingNextPage} onClick={() => parties.fetchNextPage()}>Load more</Button></div> : null}
    </div>
  );
}
