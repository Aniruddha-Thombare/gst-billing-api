import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { downloadFile, http } from "@/lib/api";
import { iso } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";
import { stateName } from "@/lib/states";

type Row = Record<string, unknown>;
interface Report extends Record<string, unknown> {
  return_period: string; financial_year: string; is_period_open: boolean; tenant: { gstin: string; legal_name: string };
  section_totals: { section: string; document_count: number; taxable_amount: string; igst_amount: string; cgst_amount: string; sgst_amount: string; cess_amount: string }[];
  net_totals: { taxable_amount: string; igst_amount: string; cgst_amount: string; sgst_amount: string; cess_amount: string }; warnings: string[];
}
const SECTIONS: [string, string][] = [["b2b", "B2B"], ["b2b_rcm", "B2B reverse charge"], ["b2cl", "B2C large"], ["b2cs", "B2C small"], ["exp", "Exports"], ["sez", "SEZ"], ["cdnr", "Credit/debit notes (registered)"], ["cdnur", "Credit/debit notes (unregistered)"], ["nil", "Nil / exempt"], ["hsn", "HSN summary"], ["docs", "Documents issued"]];

/** Column definitions per table: [row key, header, how to show it]. Money columns are strings from the API and stay strings. */
const COLS: Record<string, [string, string, "text" | "money" | "date" | "state"][]> = {
  doc: [["document_number", "Number", "text"], ["document_date", "Date", "date"], ["party_name", "Party", "text"], ["party_gstin", "GSTIN", "text"], ["place_of_supply", "Place of supply", "state"], ["taxable_amount", "Taxable", "money"], ["igst_amount", "IGST", "money"], ["cgst_amount", "CGST", "money"], ["sgst_amount", "SGST", "money"], ["document_value", "Value", "money"]],
  b2cs: [["supply_type", "Supply", "text"], ["place_of_supply", "Place of supply", "state"], ["gst_rate", "Rate %", "text"], ["taxable_amount", "Taxable", "money"], ["igst_amount", "IGST", "money"], ["cgst_amount", "CGST", "money"], ["sgst_amount", "SGST", "money"], ["document_count", "Docs", "text"]],
  nil: [["supply_type", "Supply", "text"], ["receiver", "Receiver", "text"], ["taxable_amount", "Taxable", "money"], ["document_count", "Docs", "text"]],
  hsn: [["hsn_sac_code", "HSN/SAC", "text"], ["unit", "Unit", "text"], ["gst_rate", "Rate %", "text"], ["quantity", "Quantity", "text"], ["taxable_amount", "Taxable", "money"], ["igst_amount", "IGST", "money"], ["cgst_amount", "CGST", "money"], ["sgst_amount", "SGST", "money"], ["total_value", "Total", "money"]],
  docs: [["document_type", "Type", "text"], ["series", "Series", "text"], ["first_number", "From", "text"], ["last_number", "To", "text"], ["total_numbers", "Total", "text"], ["cancelled", "Cancelled", "text"], ["net_issued", "Net issued", "text"]],
};
const colsFor = (section: string) => (section === "b2cs" || section === "nil" || section === "hsn" || section === "docs" ? COLS[section] : COLS.doc);

export function Gstr1Page() {
  const [period, setPeriod] = useState(iso(new Date()).slice(0, 7));
  const [section, setSection] = useState("b2b");
  const q = useQuery({ queryKey: ["gstr1", period], enabled: /^\d{4}-\d{2}$/.test(period), queryFn: async () => (await http.get<Report>("/gst-reports/gstr1", { params: { return_period: period } })).data });
  const r = q.data;
  const rows = ((r?.[section] as Row[] | undefined) ?? []);
  const cols = colsFor(section);
  const show = (v: unknown, kind: string) => v === null || v === undefined || v === "" ? "—" : kind === "money" ? rupees(String(v)) : kind === "date" ? fmtDate(String(v)) : kind === "state" ? stateName(String(v)) : String(v);

  return (
    <div className="space-y-6">
      <PageHeader title="GSTR-1" subtitle="Outward supplies for the return period, read-only" actions={<Input type="month" className="w-44" value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Return period" />} />
      {q.isError ? <p role="alert" className="text-destructive">{errorMessage(q.error)}</p> : null}
      {r ? <p className="text-sm text-muted-foreground">{r.tenant.legal_name} · {r.tenant.gstin} · FY {r.financial_year}{r.is_period_open ? " · period still open, figures can change" : ""}</p> : null}
      {r?.warnings.map((w) => <p key={w} className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">{w}</p>)}

      <Card className="overflow-x-auto"><CardHeader><CardTitle className="text-base">Section totals</CardTitle></CardHeader><CardContent><Table>
        <THead><TR><TH>Section</TH><TH className="text-right">Docs</TH><TH className="text-right">Taxable</TH><TH className="text-right">IGST</TH><TH className="text-right">CGST</TH><TH className="text-right">SGST</TH><TH className="text-right">Cess</TH></TR></THead>
        <TBody>
          {q.isLoading ? <TR><TD colSpan={7}><Skeleton className="h-5 w-full" /></TD></TR> : null}
          {r?.section_totals.map((s) => <TR key={s.section}><TD className="uppercase">{s.section}</TD><TD className="text-right">{s.document_count}</TD><TD className="text-right tabular-nums">{rupees(s.taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(s.igst_amount)}</TD><TD className="text-right tabular-nums">{rupees(s.cgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(s.sgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(s.cess_amount)}</TD></TR>)}
          {r ? <TR className="font-bold"><TD>Net (credit notes subtracted)</TD><TD /><TD className="text-right tabular-nums">{rupees(r.net_totals.taxable_amount)}</TD><TD className="text-right tabular-nums">{rupees(r.net_totals.igst_amount)}</TD><TD className="text-right tabular-nums">{rupees(r.net_totals.cgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(r.net_totals.sgst_amount)}</TD><TD className="text-right tabular-nums">{rupees(r.net_totals.cess_amount)}</TD></TR> : null}
        </TBody>
      </Table></CardContent></Card>

      <div className="flex flex-wrap items-center gap-2">
        {SECTIONS.map(([key, label]) => <Button key={key} size="sm" variant={section === key ? "default" : "outline"} onClick={() => setSection(key)}>{label}</Button>)}
        <Button size="sm" variant="secondary" className="ml-auto" onClick={() => downloadFile("/gst-reports/gstr1/export", { return_period: period, section }, `gstr1_${section}_${period}.csv`).catch((e) => toast.error(errorMessage(e)))}><Download className="h-4 w-4" />Download CSV</Button>
      </div>
      <Card className="overflow-x-auto"><Table>
        <THead><TR>{cols.map(([k, h, kind]) => <TH key={k} className={kind === "money" ? "text-right" : ""}>{h}</TH>)}</TR></THead>
        <TBody>
          {rows.length === 0 ? <TR><TD colSpan={cols.length} className="py-8 text-center text-muted-foreground">No rows in this section.</TD></TR> : null}
          {rows.map((row, i) => <TR key={i}>{cols.map(([k, , kind]) => <TD key={k} className={kind === "money" ? "text-right tabular-nums" : ""}>{show(row[k], kind)}</TD>)}</TR>)}
        </TBody>
      </Table></Card>
    </div>
  );
}
