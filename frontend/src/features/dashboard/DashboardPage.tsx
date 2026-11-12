import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileText, IndianRupee, Landmark, Plus, Users, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CHART, compactNumber } from "@/components/common/ChartTheme";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import type { InvoiceSummary } from "@/features/invoices/invoiceApi";
import { http, type Page } from "@/lib/api";
import { firstDayMonthsAgo, iso } from "@/lib/dates";
import { errorMessage, toApiError } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";

interface Dashboard {
  today: string; month_start: string;
  receivables: { total_outstanding: string; open_invoices: number; overdue_outstanding: string; overdue_invoices: number };
  refunds_due: { total_refund_due: string; invoices_with_refund_due: number };
  sales_this_month: { taxable_amount: string; gst_amount: string; total_amount: string };
  collections_this_month: { total_collected: string; payments_count: number };
  sales_invoice_counts_by_status: Record<string, number>;
  top_customers_by_outstanding: { party_id: string; party_name: string; outstanding: string; open_invoices: number }[];
}
interface SalesSummary { buckets: { period_label: string; net_sales_value: string; net_tax_amount: string }[] }
interface Gstr3b { total_outward: { igst_amount: string; cgst_amount: string; sgst_amount: string; cess_amount: string } }

export function DashboardPage() {
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: async () => (await http.get<Dashboard>("/dashboard")).data, retry: false });
  const sales = useQuery({
    queryKey: ["dashboard", "sales-12m"], retry: false,
    queryFn: async () => (await http.get<SalesSummary>("/reports/sales-summary", { params: { granularity: "month", from_date: firstDayMonthsAgo(11), to_date: iso(new Date()) } })).data,
  });
  const gst = useQuery({
    queryKey: ["dashboard", "gstr3b"], retry: false,
    queryFn: async () => (await http.get<Gstr3b>("/gst-reports/gstr3b", { params: { return_period: iso(new Date()).slice(0, 7) } })).data,
  });
  const recent = useQuery({ queryKey: ["invoices", "recent"], queryFn: async () => (await http.get<Page<InvoiceSummary>>("/invoices", { params: { limit: 5 } })).data.items });

  // The dashboard endpoint is not open to every role (for example auditor). Say so instead of showing a broken page.
  if (dash.isError && toApiError(dash.error).status === 403) {
    return <div><PageHeader title="Dashboard" /><p className="text-muted-foreground">Your role does not have access to the dashboard. Use Invoices, Payments and Reports from the menu.</p></div>;
  }
  const d = dash.data;
  const chartData = (sales.data?.buckets ?? []).map((b) => ({ month: b.period_label, Sales: Number(b.net_sales_value), GST: Number(b.net_tax_amount) }));
  const t = gst.data?.total_outward;
  const taxData = t ? [
    { name: "CGST", value: Number(t.cgst_amount), color: CHART.primary }, { name: "SGST", value: Number(t.sgst_amount), color: CHART.teal },
    { name: "IGST", value: Number(t.igst_amount), color: CHART.amber }, { name: "Cess", value: Number(t.cess_amount), color: CHART.rose },
  ].filter((x) => x.value > 0) : [];

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" subtitle={d ? `As of ${fmtDate(d.today)}` : "Overview of your business"} />
      {dash.isError ? <p role="alert" className="text-destructive">{errorMessage(dash.error)}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi icon={<IndianRupee />} label="Sales this month" value={d && rupees(d.sales_this_month.total_amount)} sub={d && `Taxable ${rupees(d.sales_this_month.taxable_amount)}`} tone="primary" />
        <Kpi icon={<Landmark />} label="GST this month" value={d && rupees(d.sales_this_month.gst_amount)} sub="On sales issued" tone="teal" />
        <Kpi icon={<Wallet />} label="Outstanding" value={d && rupees(d.receivables.total_outstanding)} sub={d && `${d.receivables.open_invoices} open invoices`} tone="amber" />
        <Kpi icon={<AlertTriangle />} label="Overdue" value={d && rupees(d.receivables.overdue_outstanding)} sub={d && `${d.receivables.overdue_invoices} invoices`} tone="rose" />
        <Kpi icon={<FileText />} label="Collected this month" value={d && rupees(d.collections_this_month.total_collected)} sub={d && `${d.collections_this_month.payments_count} payments`} tone="sky" />
      </div>
      {d && Number(d.refunds_due.total_refund_due) > 0 ? (
        <p className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">You owe customers {rupees(d.refunds_due.total_refund_due)} in refunds across {d.refunds_due.invoices_with_refund_due} invoice(s).</p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader><CardTitle className="text-base">Sales & GST, last 12 months</CardTitle></CardHeader><CardContent className="h-72">
          {sales.isLoading ? <Skeleton className="h-full w-full" /> : sales.isError ? <p className="text-sm text-muted-foreground">Not available for your role.</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid stroke={CHART.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} /><YAxis tickFormatter={compactNumber} tick={{ fontSize: 11 }} width={48} />
                <Tooltip formatter={(v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`} />
                <Legend />
                <Line type="monotone" dataKey="Sales" stroke={CHART.primary} strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="GST" stroke={CHART.teal} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>)}
        </CardContent></Card>

        <Card><CardHeader><CardTitle className="text-base">Tax split, this month</CardTitle></CardHeader><CardContent className="h-72">
          {gst.isLoading ? <Skeleton className="h-full w-full" /> : gst.isError ? <p className="text-sm text-muted-foreground">GST report is for owner and accountant roles.</p>
            : taxData.length === 0 ? <p className="text-sm text-muted-foreground">No tax issued this month yet.</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={taxData} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="80%" paddingAngle={2}>{taxData.map((x) => <Cell key={x.name} fill={x.color} />)}</Pie>
                <Tooltip formatter={(v: number) => `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`} /><Legend />
              </PieChart>
            </ResponsiveContainer>)}
        </CardContent></Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-x-auto lg:col-span-2"><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle className="text-base">Recent invoices</CardTitle><Button variant="ghost" size="sm" asChild><Link to="/invoices">View all</Link></Button></CardHeader><CardContent>
          <Table>
            <THead><TR><TH>Number</TH><TH>Client</TH><TH className="text-right">Total</TH><TH>Status</TH></TR></THead>
            <TBody>
              {recent.isLoading ? <TR><TD colSpan={4}><Skeleton className="h-5 w-full" /></TD></TR> : null}
              {recent.data?.length === 0 ? <TR><TD colSpan={4} className="py-6 text-center text-muted-foreground">No invoices yet.</TD></TR> : null}
              {recent.data?.map((i) => (
                <TR key={i.id}><TD><Link className="text-primary hover:underline" to={`/invoices/${i.id}`}>{i.invoice_number}</Link></TD><TD>{i.party_name ?? "—"}</TD><TD className="text-right tabular-nums">{rupees(i.total_amount)}</TD><TD><StatusBadge status={i.invoice_status} /></TD></TR>))}
            </TBody>
          </Table>
        </CardContent></Card>

        <div className="space-y-6">
          <Card><CardHeader><CardTitle className="text-base">Quick actions</CardTitle></CardHeader><CardContent className="grid gap-2">
            <Button asChild><Link to="/invoices/new"><Plus className="h-4 w-4" />New invoice</Link></Button>
            <Button variant="outline" asChild><Link to="/parties"><Users className="h-4 w-4" />Add client</Link></Button>
            <Button variant="outline" asChild><Link to="/reports/gstr1"><Landmark className="h-4 w-4" />GSTR-1 data</Link></Button>
          </CardContent></Card>
          <Card><CardHeader><CardTitle className="text-base">Biggest outstanding</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
            {d?.top_customers_by_outstanding.length === 0 ? <p className="text-muted-foreground">Nothing outstanding.</p> : null}
            {d?.top_customers_by_outstanding.map((c) => <div key={c.party_id} className="flex justify-between"><span>{c.party_name}</span><span className="tabular-nums">{rupees(c.outstanding)}</span></div>)}
          </CardContent></Card>
        </div>
      </div>
    </div>
  );
}

const TONES: Record<string, string> = { primary: "bg-primary/10 text-primary", teal: "bg-teal-500/10 text-teal-600", amber: "bg-amber-500/10 text-amber-600", rose: "bg-rose-500/10 text-rose-600", sky: "bg-sky-500/10 text-sky-600" };
function Kpi({ icon, label, value, sub, tone }: { icon: ReactNode; label: string; value?: string; sub?: string; tone: string }) {
  return (
    <Card><CardContent className="flex items-start gap-3 pt-6">
      <div className={`rounded-lg p-2 [&_svg]:h-5 [&_svg]:w-5 ${TONES[tone]}`}>{icon}</div>
      <div className="min-w-0"><div className="text-xs text-muted-foreground">{label}</div>
        <div className="truncate text-xl font-bold tabular-nums">{value ?? <Skeleton className="mt-1 h-6 w-24" />}</div>
        {sub ? <div className="text-xs text-muted-foreground">{sub}</div> : null}</div>
    </CardContent></Card>
  );
}
