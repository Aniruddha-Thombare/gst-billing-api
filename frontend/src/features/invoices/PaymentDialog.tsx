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
import { useRecordPayment } from "./invoiceApi";

const schema = z.object({
  payment_date: z.string().min(1, "Pick a date").refine((d) => d <= todayUtc(), "Cannot be in the future"),
  amount: z.string().trim().regex(/^\d+(\.\d{1,2})?$/, "Up to 2 decimals").refine((v) => Number(v) > 0, "Must be more than 0"),
  payment_mode: z.enum(["cash", "bank_transfer", "upi", "cheque", "credit_card"]),
  reference_number: z.string().trim().max(100),
  bank_name: z.string().trim().max(100),
  notes: z.string().max(1000),
}).superRefine((v, ctx) => {
  // Same rules as the backend schema, so the user is told before the request is sent.
  if (v.payment_mode !== "cash" && !v.reference_number) ctx.addIssue({ code: "custom", path: ["reference_number"], message: "Required for this payment mode" });
  if ((v.payment_mode === "cheque" || v.payment_mode === "bank_transfer") && !v.bank_name) ctx.addIssue({ code: "custom", path: ["bank_name"], message: "Required for cheque and bank transfer" });
});
type Values = z.infer<typeof schema>;

export function PaymentDialog({ open, onOpenChange, invoiceId, outstanding }: { open: boolean; onOpenChange: (o: boolean) => void; invoiceId: string; outstanding: string }) {
  const record = useRecordPayment(invoiceId);
  const idem = useIdempotencyKey();
  const [serverError, setServerError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema) });
  const mode = watch("payment_mode");

  useEffect(() => {
    if (!open) return;
    setServerError(null); setDuplicate(null); idem.reset();
    reset({ payment_date: todayUtc(), amount: outstanding, payment_mode: "bank_transfer", reference_number: "", bank_name: "", notes: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, outstanding, reset]);

  const submit = (confirmDuplicate: boolean) => handleSubmit(async (v) => {
    setServerError(null); setDuplicate(null);
    if (parseDecimal(v.amount, 2) > parseDecimal(outstanding, 2)) { setServerError(`Amount is more than the outstanding ₹${outstanding}.`); return; }
    const body = { ...v, reference_number: v.reference_number || null, bank_name: v.bank_name || null, notes: v.notes || null, confirm_duplicate: confirmDuplicate };
    try {
      await record.mutateAsync({ body, key: idem.keyFor(body) });
      idem.reset();
      toast.success("Payment recorded");
      onOpenChange(false);
    } catch (e) {
      const err = toApiError(e);
      if (err.code === "POSSIBLE_DUPLICATE_PAYMENT") setDuplicate(err.message); else setServerError(err.message);
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Record payment</DialogTitle><DialogDescription>Outstanding: ₹{outstanding}</DialogDescription></DialogHeader>
        <form onSubmit={submit(false)} noValidate className="grid gap-4 sm:grid-cols-2">
          <FormField label="Date" htmlFor="pay-date" error={errors.payment_date?.message}><Input id="pay-date" type="date" max={todayUtc()} {...register("payment_date")} /></FormField>
          <FormField label="Amount (₹)" htmlFor="pay-amount" error={errors.amount?.message}><Input id="pay-amount" inputMode="decimal" {...register("amount")} /></FormField>
          <FormField label="Mode" htmlFor="pay-mode"><Select id="pay-mode" {...register("payment_mode")}>
            <option value="bank_transfer">Bank transfer</option><option value="upi">UPI</option><option value="cheque">Cheque</option><option value="cash">Cash</option><option value="credit_card">Credit card</option>
          </Select></FormField>
          <FormField label={mode === "cash" ? "Reference (optional)" : "Reference no."} htmlFor="pay-ref" error={errors.reference_number?.message} hint="UTR, UPI ref or cheque number"><Input id="pay-ref" {...register("reference_number")} /></FormField>
          <div className="sm:col-span-2"><FormField label="Bank name" htmlFor="pay-bank" error={errors.bank_name?.message}><Input id="pay-bank" {...register("bank_name")} /></FormField></div>
          <div className="sm:col-span-2"><FormField label="Notes (optional)" htmlFor="pay-notes"><Textarea id="pay-notes" {...register("notes")} /></FormField></div>
          {duplicate ? (
            <div role="alert" className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm sm:col-span-2">
              <p>{duplicate}</p><Button type="button" size="sm" variant="outline" className="mt-2" onClick={submit(true)}>It is a separate payment, record anyway</Button>
            </div>
          ) : null}
          {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive sm:col-span-2">{serverError}</p> : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={record.isPending}>{record.isPending ? "Saving…" : "Record payment"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
