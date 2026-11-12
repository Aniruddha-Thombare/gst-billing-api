import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/common/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { http } from "@/lib/api";
import { iso } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import { rupees } from "@/lib/format";
import { stateName } from "@/lib/states";

interface Tax { taxable_amount: string; igst_amount: string; cgst_amount: string; sgst_amount: string; cess_amount: string; }
interface Report { return_period: string; financial_year: string; is_period_open: boolean; tenant: { gstin: string; legal_name: string };
  outward_taxable: Tax; outward_zero_rated: Tax; outward_nil_exempt: Tax; outward_reverse_charge: Tax; total_outward: Tax;
  unregistered_interstate: { place_of_supply: string; taxable_amount: string; igst_amount: string }[]; warnings: string[]; }

export function Gstr3bPage() {
  const [period, setPeriod] = useState(iso(new Date()).slice(0, 7));
  const q = useQuery({ queryKey: ["gstr3b", period], enabled: /^\d{4}-\d{2}$/.test(period), queryFn: async () => (await http.get<Report>("/gst-reports/gstr3b", { params: { return_period: period } })).data });
  const r = q.data;
  const rows: [string, Tax | undefined, boolean?][] = [
    ["3.1(a) Outward taxable supplies", r?.outward_taxable], ["3.1(b) Zero rated (exports, SEZ)", r?.outward_zero_rated],
    ["3.1(c) Nil rated and exempt", r?.outward_nil_exempt], ["Total outward (a + b + c)", r?.total_outward, true],
    ["Reverse charge (information only, not in total)", r?.outward_reverse_charge],
  ];
  return (
    <div className="space-y-6">
      <PageHeader title="GSTR-3B" subtitle="Outward supplies summary, read-only" actions={<Input type="month" className="w-44" value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Return period" />} />
      {q.isError ? <p role="alert" className="text-destructive">{errorMessage(q.error)}</p> : null}
      {r ? <p className="text-sm text-muted-foreground">{r.tenant.legal_name} · {r.tenant.gstin} · FY {r.financial_year}{r.is_period_open ? " · period still open" : ""}</p> : null}
      {r?.warnings.map((w) => <p key={w} className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">{w}</p>)}
      <Card className="overflow-x-auto"><CardHeader><CardTitle className="text-base">Table 3.1</CardTitle></CardHeader><CardContent><Table>
        <THead><TR><TH>Nature of supply</TH><TH className="text-right">Taxable</TH><TH className="text-right">IGST</TH><TH className="text-right">CGST</TH><TH className="text-right">SGST</TH><TH className="text-right">Cess</TH></TR></THead>
        <TBody>
          {q.isLoading ? <TR><TD colSpan={6}><Skeleton className="h-5 w-full" /></TD></TR> : null}
          {rows.map(([label, t, bold]) => t ? (
            <TR key={label} className={bold ? "font-bold" : ""}><TD>{label}</TD><TD className="text-right tabular-nums">{rupees(t.taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(t.igst_amount)}</TD><TD className="text-right tabular-nums">{rupees(t.cgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(t.sgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(t.cess_amount)}</TD></TR>) : null)}
        </TBody>
      </Table></CardContent></Card>
      <Card className="overflow-x-auto"><CardHeader><CardTitle className="text-base">Table 3.2: inter-state supplies to unregistered persons</CardTitle></CardHeader><CardContent><Table>
        <THead><TR><TH>Place of supply</TH><TH className="text-right">Taxable</TH><TH className="text-right">IGST</TH></TR></THead>
        <TBody>
          {r?.unregistered_interstate.length === 0 ? <TR><TD colSpan={3} className="py-6 text-center text-muted-foreground">None this period.</TD></TR> : null}
          {r?.unregistered_interstate.map((x) => <TR key={x.place_of_supply}><TD>{stateName(x.place_of_supply)}</TD><TD className="text-right tabular-nums">{rupees(x.taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(x.igst_amount)}</TD></TR>)}
        </TBody>
      </Table></CardContent></Card>
    </div>
  );
}
