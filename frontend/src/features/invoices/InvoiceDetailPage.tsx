import { ArrowLeft, Download, Send } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/PageHeader";
import { ReasonDialog } from "@/components/common/ReasonDialog";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useCanWrite } from "@/features/auth/AuthContext";
import { useIdempotencyKey } from "@/hooks/useIdempotencyKey";
import { openPdf } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fmtDate, rupees } from "@/lib/format";
import { stateName } from "@/lib/states";
import { useCancelPayment, useCancelRefund, useInvoice, useInvoicePayments, useInvoiceRefunds, useSendInvoice, useVoidInvoice } from "./invoiceApi";
import { PaymentDialog } from "./PaymentDialog";
import { RefundDialog } from "./RefundDialog";

export function InvoiceDetailPage() {
  const { id = "" } = useParams();
  const canWrite = useCanWrite();
  const invoiceQuery = useInvoice(id);
  const paymentsQuery = useInvoicePayments(id);
  const send = useSendInvoice(id);
  const voidInvoice = useVoidInvoice(id);
  const cancelPayment = useCancelPayment(id);
  const refundsQuery = useInvoiceRefunds(id);
  const cancelRefund = useCancelRefund(id);
  const navigate = useNavigate();
  const sendKey = useIdempotencyKey();
  const [refundOpen, setRefundOpen] = useState(false);
  const [cancelRefundId, setCancelRefundId] = useState<string | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [voidOpen, setVoidOpen] = useState(false);
  const [cancelId, setCancelId] = useState<string | null>(null);

  if (invoiceQuery.isLoading) return <div className="space-y-3"><Skeleton className="h-10 w-64" /><Skeleton className="h-64 w-full" /></div>;
  if (invoiceQuery.isError || !invoiceQuery.data) return <p role="alert" className="text-destructive">{errorMessage(invoiceQuery.error)}</p>;
  const inv = invoiceQuery.data;

  const status = inv.invoice_status;
  const isDraft = status === "draft";
  const canReceive = inv.invoice_type === "sales" && ["sent", "partial", "overdue"].includes(status);
  const refundDue = Number(inv.refund_due_amount) > 0;
  // Locked invoices are never edited. A mistake after sending is corrected with a credit note (less) or debit note (more).
  const canCorrect = inv.invoice_type === "sales" && ["sent", "partial", "paid", "overdue"].includes(status);
  const canVoid = status === "sent" && Number(inv.paid_amount) === 0; // the server decides for real; this only hides a useless button
  const pdf = (path: string) => openPdf(path).catch((e) => toast.error(errorMessage(e)));

  const doSend = () => send.mutate(sendKey.keyFor({ id }), {
    onSuccess: () => { sendKey.reset(); toast.success("Invoice sent and locked"); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="space-y-6">
      <Link to="/invoices" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />Invoices</Link>
      <PageHeader
        title={inv.invoice_number}
        subtitle={`${inv.invoice_type.replace("_", " ")} · ${fmtDate(inv.invoice_date)}${inv.due_date ? ` · due ${fmtDate(inv.due_date)}` : ""} · FY ${inv.financial_year}`}
        actions={<>
          <StatusBadge status={status} />
          {!isDraft ? <Button variant="outline" onClick={() => pdf(`/invoices/${id}/pdf`)}><Download className="h-4 w-4" />PDF</Button> : null}
          {canWrite && isDraft ? <Button disabled={send.isPending} onClick={doSend}><Send className="h-4 w-4" />{send.isPending ? "Sending…" : "Send invoice"}</Button> : null}
          {canWrite && canReceive ? <Button onClick={() => setPayOpen(true)}>Record payment</Button> : null}
          {canWrite && refundDue ? <Button onClick={() => setRefundOpen(true)}>Record refund</Button> : null}
          {canWrite && canCorrect ? <Button variant="outline" onClick={() => navigate(`/invoices/new?type=credit_note&original=${id}`)}>Credit note</Button> : null}
          {canWrite && canCorrect ? <Button variant="outline" onClick={() => navigate(`/invoices/new?type=debit_note&original=${id}`)}>Debit note</Button> : null}
          {canWrite && canVoid ? <Button variant="destructive" onClick={() => setVoidOpen(true)}>Void</Button> : null}
        </>}
      />
      {isDraft ? <p className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">This is a draft. Sending it locks it permanently: after that it can only be voided (if unpaid) or corrected with a credit note.</p> : null}
      {status === "void" ? <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm">Voided {fmtDate(inv.voided_at)}. Reason: {inv.void_reason}</p> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card><CardHeader><CardTitle className="text-base">Party (snapshot at issue)</CardTitle></CardHeader><CardContent className="space-y-1 text-sm">
          <div className="font-mono">{inv.party_gstin ?? "Unregistered (B2C)"}</div>
          <div>State: {stateName(inv.party_state_code)}</div><div>Place of supply: {stateName(inv.place_of_supply)}</div>
          <div className="capitalize">Supply: {inv.supply_type.replace("_", "-")}</div>{inv.reverse_charge ? <div>Reverse charge applies</div> : null}
        </CardContent></Card>
        <Card className="lg:col-span-2"><CardHeader><CardTitle className="text-base">Totals</CardTitle></CardHeader><CardContent className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
          <Row l="Subtotal" v={inv.subtotal} /><Row l="Discount" v={inv.discount_amount} /><Row l="Taxable value" v={inv.taxable_amount} />
          <Row l="CGST" v={inv.cgst_amount} /><Row l="SGST" v={inv.sgst_amount} /><Row l="IGST" v={inv.igst_amount} /><Row l="Cess" v={inv.cess_amount} />
          <Row l="Total" v={inv.total_amount} bold />
          {!isDraft ? <><Row l="Paid" v={inv.paid_amount} /><Row l="Credited" v={inv.credited_amount} /><Row l="Refunded" v={inv.refunded_amount} />
            <Row l="Outstanding" v={inv.outstanding_amount} bold />{Number(inv.refund_due_amount) > 0 ? <Row l="Refund due to customer" v={inv.refund_due_amount} bold /> : null}</> : null}
        </CardContent></Card>
      </div>

      <Card className="overflow-x-auto"><Table>
        <THead><TR><TH>#</TH><TH>Description</TH><TH>HSN/SAC</TH><TH className="text-right">Qty</TH><TH className="text-right">Rate</TH><TH className="text-right">Disc</TH><TH className="text-right">Taxable</TH><TH className="text-right">GST</TH><TH className="text-right">Total</TH></TR></THead>
        <TBody>{inv.line_items.map((l) => (
          <TR key={l.id}>
            <TD>{l.line_number}</TD><TD>{l.description}</TD><TD className="font-mono text-xs">{l.hsn_sac_code ?? "—"}</TD>
            <TD className="text-right tabular-nums">{Number(l.quantity)} {l.unit ?? ""}</TD><TD className="text-right tabular-nums">{rupees(l.rate)}</TD>
            <TD className="text-right tabular-nums">{rupees(l.discount_amount)}</TD><TD className="text-right tabular-nums">{rupees(l.taxable_amount)}</TD>
            <TD className="text-right tabular-nums">{Number(l.gst_rate)}%<div className="text-xs text-muted-foreground">{Number(l.igst_amount) > 0 ? `IGST ${rupees(l.igst_amount)}` : `C ${rupees(l.cgst_amount)} · S ${rupees(l.sgst_amount)}`}</div></TD>
            <TD className="text-right font-medium tabular-nums">{rupees(l.total_amount)}</TD>
          </TR>))}
        </TBody>
      </Table></Card>

      {inv.notes ? <p className="whitespace-pre-wrap text-sm text-muted-foreground">Notes: {inv.notes}</p> : null}

      {!isDraft ? (
        <Card className="overflow-x-auto"><CardHeader><CardTitle className="text-base">Payments</CardTitle></CardHeader><CardContent>
          <Table>
            <THead><TR><TH>Number</TH><TH>Date</TH><TH>Mode</TH><TH>Reference</TH><TH className="text-right">Amount</TH><TH>Status</TH><TH className="text-right">Actions</TH></TR></THead>
            <TBody>
              {paymentsQuery.isLoading ? <TR><TD colSpan={7}><Skeleton className="h-5 w-full" /></TD></TR> : null}
              {paymentsQuery.data?.length === 0 ? <TR><TD colSpan={7} className="py-6 text-center text-muted-foreground">No payments yet.</TD></TR> : null}
              {paymentsQuery.data?.map((p) => (
                <TR key={p.id}>
                  <TD className="font-medium">{p.payment_number}</TD><TD>{fmtDate(p.payment_date)}</TD><TD className="capitalize">{p.payment_mode.replace("_", " ")}</TD>
                  <TD>{p.reference_number ?? "—"}</TD><TD className="text-right tabular-nums">{rupees(p.amount)}</TD><TD><StatusBadge status={p.status} /></TD>
                  <TD className="space-x-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => pdf(`/payments/${p.id}/pdf`)}>Receipt</Button>
                    {canWrite && p.status === "active" ? <Button size="sm" variant="ghost" onClick={() => setCancelId(p.id)}>Cancel</Button> : null}
                  </TD>
                </TR>))}
            </TBody>
          </Table>
        </CardContent></Card>
      ) : null}

      {(refundsQuery.data?.length ?? 0) > 0 ? (
        <Card className="overflow-x-auto"><CardHeader><CardTitle className="text-base">Refunds</CardTitle></CardHeader><CardContent>
          <Table>
            <THead><TR><TH>Number</TH><TH>Date</TH><TH>Mode</TH><TH>Reference</TH><TH className="text-right">Amount</TH><TH>Status</TH><TH className="text-right">Actions</TH></TR></THead>
            <TBody>{refundsQuery.data!.map((r) => (
              <TR key={r.id}>
                <TD className="font-medium">{r.refund_number}</TD><TD>{fmtDate(r.refund_date)}</TD><TD className="capitalize">{r.refund_mode.replace("_", " ")}</TD>
                <TD>{r.reference_number ?? "—"}</TD><TD className="text-right tabular-nums">{rupees(r.amount)}</TD><TD><StatusBadge status={r.status} /></TD>
                <TD className="space-x-2 text-right">
                  <Button size="sm" variant="outline" onClick={() => pdf(`/refunds/${r.id}/pdf`)}>Voucher</Button>
                  {canWrite && r.status === "active" ? <Button size="sm" variant="ghost" onClick={() => setCancelRefundId(r.id)}>Cancel</Button> : null}
                </TD>
              </TR>))}
            </TBody>
          </Table>
        </CardContent></Card>
      ) : null}

      <RefundDialog open={refundOpen} onOpenChange={setRefundOpen} invoiceId={id} refundDue={inv.refund_due_amount} />
      <ReasonDialog open={cancelRefundId !== null} onOpenChange={(o) => !o && setCancelRefundId(null)} title="Cancel this refund?" description="The refund stays on record as cancelled and the refund due is restored." confirmLabel="Cancel refund"
        onConfirm={async (reason) => { await cancelRefund.mutateAsync({ refundId: cancelRefundId!, reason }); toast.success("Refund cancelled"); }} />
      <PaymentDialog open={payOpen} onOpenChange={setPayOpen} invoiceId={id} outstanding={inv.outstanding_amount} />
      <ReasonDialog open={voidOpen} onOpenChange={setVoidOpen} title="Void this invoice?" description="The invoice stays on record as void. This cannot be undone." confirmLabel="Void invoice"
        onConfirm={async (reason) => { await voidInvoice.mutateAsync(reason); toast.success("Invoice voided"); }} />
      <ReasonDialog open={cancelId !== null} onOpenChange={(o) => !o && setCancelId(null)} title="Cancel this payment?" description="The payment is kept on record as cancelled and the invoice balance is restored." confirmLabel="Cancel payment"
        onConfirm={async (reason) => { await cancelPayment.mutateAsync({ paymentId: cancelId!, reason }); toast.success("Payment cancelled"); }} />
    </div>
  );
}

function Row({ l, v, bold }: { l: string; v: string; bold?: boolean }) {
  return <div className={`flex justify-between ${bold ? "font-bold" : ""}`}><span className={bold ? "" : "text-muted-foreground"}>{l}</span><span className="tabular-nums">{rupees(v)}</span></div>;
}
