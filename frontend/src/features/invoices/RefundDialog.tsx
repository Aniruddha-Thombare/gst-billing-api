import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useIdempotencyKey } from "@/hooks/useIdempotencyKey";
import { toApiError } from "@/lib/errors";
import { todayUtc } from "@/lib/format";
import { parseDecimal } from "@/lib/money";
import { useRecordRefund } from "./invoiceApi";

const schema = z.object({
  refund_date: z.string().min(1, "Pick a date").refine((d) => d <= todayUtc(), "Cannot be in the future"),
  amount: z.string().trim().regex(/^\d+(\.\d{1,2})?$/, "Up to 2 decimals").refine((v) => Number(v) > 0, "Must be more than 0"),
  refund_mode: z.enum(["cash", "bank_transfer", "upi", "cheque", "credit_card"]),
  reference_number: z.string().trim().max(100),
  bank_name: z.string().trim().max(100),
  notes: z.string().max(1000),
}).superRefine((v, ctx) => {
  if (v.refund_mode !== "cash" && !v.reference_number) ctx.addIssue({ code: "custom", path: ["reference_number"], message: "Required for this refund mode" });
});
type Values = z.infer<typeof schema>;

/** Refund = money going BACK to the customer, only possible while "refund due" is above zero (after a credit note on a paid invoice). */
export function RefundDialog({ open, onOpenChange, invoiceId, refundDue }: { open: boolean; onOpenChange: (o: boolean) => void; invoiceId: string; refundDue: string }) {
  const record = useRecordRefund(invoiceId);
  const idem = useIdempotencyKey();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (!open) return;
    setServerError(null); idem.reset();
    reset({ refund_date: todayUtc(), amount: refundDue, refund_mode: "bank_transfer", reference_number: "", bank_name: "", notes: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, refundDue, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    if (parseDecimal(v.amount, 2) > parseDecimal(refundDue, 2)) { setServerError(`Amount is more than the refund due ₹${refundDue}.`); return; }
    const body = { ...v, reference_number: v.reference_number || null, bank_name: v.bank_name || null, notes: v.notes || null };
    try {
      await record.mutateAsync({ body, key: idem.keyFor(body) });
      idem.reset(); toast.success("Refund recorded"); onOpenChange(false);
    } catch (e) { setServerError(toApiError(e).message); }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Record refund</DialogTitle><DialogDescription>Refund due to the customer: ₹{refundDue}</DialogDescription></DialogHeader>
        <form onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2">
          <FormField label="Date" htmlFor="rf-date" error={errors.refund_date?.message}><Input id="rf-date" type="date" max={todayUtc()} {...register("refund_date")} /></FormField>
          <FormField label="Amount (₹)" htmlFor="rf-amt" error={errors.amount?.message}><Input id="rf-amt" inputMode="decimal" {...register("amount")} /></FormField>
          <FormField label="Mode" htmlFor="rf-mode"><Select id="rf-mode" {...register("refund_mode")}>
            <option value="bank_transfer">Bank transfer</option><option value="upi">UPI</option><option value="cheque">Cheque</option><option value="cash">Cash</option><option value="credit_card">Credit card</option>
          </Select></FormField>
          <FormField label="Reference no." htmlFor="rf-ref" error={errors.reference_number?.message}><Input id="rf-ref" {...register("reference_number")} /></FormField>
          <div className="sm:col-span-2"><FormField label="Bank name (optional)" htmlFor="rf-bank"><Input id="rf-bank" {...register("bank_name")} /></FormField></div>
          <div className="sm:col-span-2"><FormField label="Notes (optional)" htmlFor="rf-notes"><Textarea id="rf-notes" {...register("notes")} /></FormField></div>
          {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive sm:col-span-2">{serverError}</p> : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={record.isPending}>{record.isPending ? "Saving…" : "Record refund"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
