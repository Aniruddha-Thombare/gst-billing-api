import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useCanWrite } from "@/features/auth/AuthContext";
import { usePagedList } from "@/hooks/usePagedList";
import { errorMessage } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";
import type { InvoiceSummary } from "./invoiceApi";

const TYPE_LABEL: Record<string, string> = { sales: "Sales", purchase: "Purchase", credit_note: "Credit note", debit_note: "Debit note" };

export function InvoicesPage({ notes = false }: { notes?: boolean }) {
  const canWrite = useCanWrite();
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [type, setType] = useState(notes ? "credit_note" : "");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = usePagedList<InvoiceSummary>("invoices", "/invoices", { status, invoice_type: type, date_from: from, date_to: to });

  return (
    <div>
      <PageHeader title={notes ? "Credit / Debit Notes" : "Invoices"} subtitle={notes ? "Issued from an invoice's page, to correct it after it was sent" : "Newest first"} actions={canWrite && !notes ? <Button asChild><Link to="/invoices/new"><Plus className="h-4 w-4" />New invoice</Link></Button> : null} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select className="w-40" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All statuses</option>
          {["draft", "sent", "partial", "paid", "overdue", "void", "cancelled"].map((s) => <option key={s} value={s} className="capitalize">{s}</option>)}
        </Select>
        <Select className="w-44" value={type} onChange={(e) => setType(e.target.value)} aria-label="Type">
          {notes ? null : <option value="">All types</option>}
          {Object.entries(TYPE_LABEL).filter(([v]) => !notes || v.endsWith("_note")).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">From<Input type="date" className="w-40" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">To<Input type="date" className="w-40" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead><TR><TH>Number</TH><TH>Date</TH><TH>Client</TH><TH>Type</TH><TH className="text-right">Total</TH><TH className="text-right">Outstanding</TH><TH>Status</TH></TR></THead>
          <TBody>
            {list.isLoading ? Array.from({ length: 6 }).map((_, i) => <TR key={i}><TD colSpan={7}><Skeleton className="h-5 w-full" /></TD></TR>) : null}
            {list.isError ? <TR><TD colSpan={7} className="text-destructive">{errorMessage(list.error)}</TD></TR> : null}
            {!list.isLoading && !list.isError && list.rows.length === 0 ? <TR><TD colSpan={7} className="py-8 text-center text-muted-foreground">No invoices match these filters.</TD></TR> : null}
            {list.rows.map((inv) => (
              <TR key={inv.id} className="cursor-pointer hover:bg-muted/50" onClick={() => navigate(`/invoices/${inv.id}`)}>
                <TD className="font-medium"><Link className="text-primary hover:underline" to={`/invoices/${inv.id}`} onClick={(e) => e.stopPropagation()}>{inv.invoice_number}</Link></TD>
                <TD>{fmtDate(inv.invoice_date)}</TD>
                <TD>{inv.party_name ?? <span className="font-mono text-xs">{inv.party_gstin ?? "—"}</span>}</TD>
                <TD>{TYPE_LABEL[inv.invoice_type] ?? inv.invoice_type}</TD>
                <TD className="text-right tabular-nums">{rupees(inv.total_amount)}</TD>
                {/* Outstanding is meaningless for a draft (it just equals the total), so hide it. */}
                <TD className="text-right tabular-nums">{inv.invoice_status === "draft" ? "—" : rupees(inv.outstanding_amount)}</TD>
                <TD><StatusBadge status={inv.invoice_status} /></TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      {list.hasNextPage ? <div className="mt-4 text-center"><Button variant="outline" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{list.isFetchingNextPage ? "Loading…" : "Load more"}</Button></div> : null}
    </div>
  );
}
