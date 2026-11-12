import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import type { Payment } from "@/features/invoices/invoiceApi";
import { usePagedList } from "@/hooks/usePagedList";
import { openPdf } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";

export function PaymentsPage() {
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = usePagedList<Payment>("payments-all", "/payments", { status, date_from: from, date_to: to });
  return (
    <div>
      <PageHeader title="Payments" subtitle="Money received, newest first. Record a payment from an invoice's page." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select className="w-40" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All</option><option value="active">Active</option><option value="cancelled">Cancelled</option>
        </Select>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">From<Input type="date" className="w-40" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">To<Input type="date" className="w-40" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      <Card className="overflow-x-auto"><Table>
        <THead><TR><TH>Number</TH><TH>Date</TH><TH>Mode</TH><TH>Reference</TH><TH className="text-right">Amount</TH><TH>Status</TH><TH className="text-right">Invoice</TH></TR></THead>
        <TBody>
          {list.isLoading ? Array.from({ length: 5 }).map((_, i) => <TR key={i}><TD colSpan={7}><Skeleton className="h-5 w-full" /></TD></TR>) : null}
          {list.isError ? <TR><TD colSpan={7} className="text-destructive">{errorMessage(list.error)}</TD></TR> : null}
          {!list.isLoading && !list.isError && list.rows.length === 0 ? <TR><TD colSpan={7} className="py-8 text-center text-muted-foreground">No payments found.</TD></TR> : null}
          {list.rows.map((p) => (
            <TR key={p.id}>
              <TD className="font-medium">{p.payment_number}</TD><TD>{fmtDate(p.payment_date)}</TD><TD className="capitalize">{p.payment_mode.replace("_", " ")}</TD>
              <TD>{p.reference_number ?? "—"}</TD><TD className="text-right tabular-nums">{rupees(p.amount)}</TD><TD><StatusBadge status={p.status} /></TD>
              <TD className="space-x-2 text-right">
                <Button size="sm" variant="outline" onClick={() => openPdf(`/payments/${p.id}/pdf`).catch((e) => toast.error(errorMessage(e)))}>Receipt</Button>
                <Button size="sm" variant="ghost" asChild><Link to={`/invoices/${p.invoice_id}`}>Open</Link></Button>
              </TD>
            </TR>))}
        </TBody>
      </Table></Card>
      {list.hasNextPage ? <div className="mt-4 text-center"><Button variant="outline" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{list.isFetchingNextPage ? "Loading…" : "Load more"}</Button></div> : null}
    </div>
  );
}
