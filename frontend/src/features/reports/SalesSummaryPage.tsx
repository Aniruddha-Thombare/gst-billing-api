import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART, compactNumber } from "@/components/common/ChartTheme";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { http } from "@/lib/api";
import { financialYearStart, iso } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import { rupees } from "@/lib/format";

interface Bucket { period_label: string; sales_count: number; credit_note_count: number; debit_note_count: number; gross_sales_value: string; credit_note_value: string; net_sales_value: string; net_taxable_amount: string; net_tax_amount: string; }
interface Report { buckets: Bucket[]; totals: Bucket; }

export function SalesSummaryPage() {
  const [granularity, setGranularity] = useState("month");
  const [from, setFrom] = useState(financialYearStart());
  const [to, setTo] = useState(iso(new Date()));
  const q = useQuery({
    queryKey: ["sales-summary", granularity, from, to], enabled: Boolean(from && to && from <= to),
    queryFn: async () => (await http.get<Report>("/reports/sales-summary", { params: { granularity, from_date: from, to_date: to } })).data,
  });
  const data = (q.data?.buckets ?? []).map((b) => ({ period: b.period_label, "Net sales": Number(b.net_sales_value), "Net tax": Number(b.net_tax_amount) }));
  return (
    <div className="space-y-6">
      <PageHeader title="Sales Summary" subtitle="Net of credit notes" />
      <div className="flex flex-wrap items-center gap-3">
        <Select className="w-40" value={granularity} onChange={(e) => setGranularity(e.target.value)} aria-label="Group by">
          <option value="week">Weekly</option><option value="month">Monthly</option><option value="quarter">Quarterly</option><option value="year">Financial year</option>
        </Select>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">From<Input type="date" className="w-40" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">To<Input type="date" className="w-40" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      {q.isError ? <p role="alert" className="text-destructive">{errorMessage(q.error)}</p> : null}
      <Card><CardContent className="h-72 pt-6">
        {q.isLoading ? <Skeleton className="h-full w-full" /> : (
          <ResponsiveContainer width="100%" height="100%"><BarChart data={data}>
            <CartesianGrid stroke={CHART.grid} strokeDasharray="3 3" vertical={false} /><XAxis dataKey="period" tick={{ fontSize: 11 }} /><YAxis tickFormatter={compactNumber} width={48} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`} /><Legend />
            <Bar dataKey="Net sales" fill={CHART.primary} radius={[4, 4, 0, 0]} /><Bar dataKey="Net tax" fill={CHART.teal} radius={[4, 4, 0, 0]} />
          </BarChart></ResponsiveContainer>)}
      </CardContent></Card>
      <Card className="overflow-x-auto"><Table>
        <THead><TR><TH>Period</TH><TH className="text-right">Invoices</TH><TH className="text-right">Credit notes</TH><TH className="text-right">Gross sales</TH><TH className="text-right">Credit note value</TH><TH className="text-right">Net taxable</TH><TH className="text-right">Net tax</TH><TH className="text-right">Net sales</TH></TR></THead>
        <TBody>
          {q.data?.buckets.map((b) => (
            <TR key={b.period_label}><TD>{b.period_label}</TD><TD className="text-right">{b.sales_count}</TD><TD className="text-right">{b.credit_note_count}</TD>
              <TD className="text-right tabular-nums">{rupees(b.gross_sales_value)}</TD><TD className="text-right tabular-nums">{rupees(b.credit_note_value)}</TD><TD className="text-right tabular-nums">{rupees(b.net_taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(b.net_tax_amount)}</TD><TD className="text-right font-medium tabular-nums">{rupees(b.net_sales_value)}</TD></TR>))}
          {q.data ? <TR className="font-bold"><TD>Total</TD><TD className="text-right">{q.data.totals.sales_count}</TD><TD className="text-right">{q.data.totals.credit_note_count}</TD>
            <TD className="text-right tabular-nums">{rupees(q.data.totals.gross_sales_value)}</TD><TD className="text-right tabular-nums">{rupees(q.data.totals.credit_note_value)}</TD><TD className="text-right tabular-nums">{rupees(q.data.totals.net_taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(q.data.totals.net_tax_amount)}</TD><TD className="text-right tabular-nums">{rupees(q.data.totals.net_sales_value)}</TD></TR> : null}
        </TBody>
      </Table></Card>
    </div>
  );
}
