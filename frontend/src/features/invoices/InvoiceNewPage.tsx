import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Item } from "@/features/items/itemApi";
import type { Party } from "@/features/parties/partyApi";
import { useIdempotencyKey } from "@/hooks/useIdempotencyKey";
import { http, type Page } from "@/lib/api";
import { toApiError } from "@/lib/errors";
import { formatINR, todayUtc } from "@/lib/format";
import { calcInvoice, toPlain } from "@/lib/money";
import { GST_SLABS } from "@/lib/states";
import { useCreateInvoice, useInvoice } from "./invoiceApi";

const decimal = (places: number, msg: string) => z.string().trim().regex(new RegExp(`^\\d+(\\.\\d{1,${places}})?$`), msg);
const lineSchema = z.object({
  description: z.string().trim().min(1, "Describe the item").max(500),
  hsn_sac_code: z.string().trim().regex(/^[0-9]{4,8}$/, "4 to 8 digits").or(z.literal("")),
  quantity: decimal(3, "Up to 3 decimals").refine((v) => Number(v) > 0, "Must be more than 0"),
  unit: z.string().trim().max(10),
  rate: decimal(4, "Up to 4 decimals").refine((v) => Number(v) > 0, "Must be more than 0"),
  discount_percent: decimal(2, "0 to 100").refine((v) => Number(v) <= 100, "At most 100"),
  gst_rate: z.string().refine((v) => GST_SLABS.includes(v), "Choose a slab"),
  cess_rate: decimal(2, "Up to 2 decimals"),
});
const schema = z.object({
  invoice_type: z.enum(["sales", "purchase", "credit_note", "debit_note"]),
  party_id: z.string().min(1, "Choose a client"),
  invoice_date: z.string().min(1, "Pick a date").refine((d) => d <= todayUtc(), "Cannot be in the future"),
  due_date: z.string(),
  is_service: z.boolean(),
  notes: z.string().max(2000),
  line_items: z.array(lineSchema).min(1, "Add at least one line").max(100),
}).refine((v) => !v.due_date || v.due_date >= v.invoice_date, { path: ["due_date"], message: "Due date cannot be before the invoice date" });
type Values = z.infer<typeof schema>;

const blankLine = { description: "", hsn_sac_code: "", quantity: "1", unit: "NOS", rate: "", discount_percent: "0", gst_rate: "18", cess_rate: "0" };

export function InvoiceNewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const noteType = params.get("type") === "credit_note" || params.get("type") === "debit_note" ? (params.get("type") as "credit_note" | "debit_note") : null;
  const originalId = noteType ? params.get("original") ?? "" : "";
  const original = useInvoice(originalId);
  const create = useCreateInvoice();
  const idem = useIdempotencyKey();
  const [serverError, setServerError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<string | null>(null);

  const { register, control, handleSubmit, watch, reset, formState: { errors, isSubmitting } } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { invoice_type: noteType ?? "sales", party_id: "", invoice_date: todayUtc(), due_date: "", is_service: false, notes: "", line_items: [{ ...blankLine }] },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "line_items" });

  const type = watch("invoice_type");
  const isNote = noteType !== null;

  // A note starts as a copy of the original invoice: same client, same lines. Edit quantities to what is being credited/debited.
  const orig = original.data;
  useEffect(() => {
    if (!isNote || !orig) return;
    reset({
      invoice_type: noteType!, party_id: orig.party_id, invoice_date: todayUtc(), due_date: "",
      is_service: orig.line_items.some((l) => l.hsn_sac_code?.startsWith("99")), notes: "",
      line_items: orig.line_items.map((l) => ({
        description: l.description, hsn_sac_code: l.hsn_sac_code ?? "", quantity: String(Number(l.quantity)), unit: l.unit ?? "",
        rate: String(Number(l.rate)), discount_percent: String(Number(l.discount_percent)),
        gst_rate: GST_SLABS.find((sl) => Number(sl) === Number(l.gst_rate)) ?? "18", cess_rate: String(Number(l.cess_rate)),
      })),
    });
  }, [isNote, orig, noteType, reset]);
  const originalParty = useQuery({
    queryKey: ["party", orig?.party_id], enabled: isNote && !!orig,
    queryFn: async () => (await http.get<Party>(`/parties/${orig!.party_id}`)).data,
  });
  const parties = useQuery({
    queryKey: ["parties", "picker", type],
    enabled: !isNote,
    queryFn: async () => (await http.get<Page<Party>>("/parties", { params: { party_type: type === "purchase" ? "vendor" : "customer", is_active: true, limit: 100 } })).data.items,
  });
  const items = useQuery({ queryKey: ["items", "picker"], queryFn: async () => (await http.get<Page<Item>>("/items", { params: { is_active: true, limit: 100 } })).data.items });

  // Live preview: recalculated in the browser with BigInt maths. Invalid input simply shows no preview.
  // watch() hands back the same array object even after an edit, so we key the memo on a JSON snapshot.
  const linesSnapshot = JSON.stringify(watch("line_items"));
  const preview = useMemo(() => previewOf(JSON.parse(linesSnapshot) as Values["line_items"]), [linesSnapshot]);

  const addFromItem = (id: string) => {
    const item = items.data?.find((i) => i.id === id);
    if (!item) return;
    append({
      ...blankLine, description: item.name, hsn_sac_code: item.hsn_sac_code ?? "", unit: item.unit, rate: item.rate,
      gst_rate: GST_SLABS.find((s) => Number(s) === Number(item.gst_rate)) ?? "18", cess_rate: String(Number(item.cess_rate)),
    });
  };

  const submit = (confirmDuplicate: boolean) => handleSubmit(async (v) => {
    setServerError(null); setDuplicateWarning(null);
    // Recalculate from the exact values being sent, never from what is currently on screen.
    const totals = previewOf(v.line_items);
    if (!totals) { setServerError("Fill in valid amounts first."); return; }
    const body = {
      invoice_type: v.invoice_type, invoice_date: v.invoice_date, due_date: v.due_date || null, party_id: v.party_id,
      is_service: v.is_service, original_invoice_id: isNote ? originalId : undefined, notes: v.notes || null, confirm_duplicate: confirmDuplicate,
      line_items: v.line_items.map((l) => ({ ...l, hsn_sac_code: l.hsn_sac_code || null, unit: l.unit || null })),
      // The server re-computes everything and rejects a total that differs beyond a rounding tolerance.
      declared_grand_total: toPlain(totals.grand),
    };
    try {
      const invoice = await create.mutateAsync({ body, key: idem.keyFor(body) });
      idem.reset();
      toast.success(`Draft ${invoice.invoice_number} created`);
      navigate(`/invoices/${invoice.id}`);
    } catch (e) {
      const err = toApiError(e);
      if (err.code === "POSSIBLE_DUPLICATE_INVOICE") setDuplicateWarning(err.message);
      else setServerError(err.message);
    }
  });

  const cell = "space-y-1";
  return (
    <div>
      <PageHeader
        title={noteType === "credit_note" ? "New credit note" : noteType === "debit_note" ? "New debit note" : "New invoice"}
        subtitle={isNote ? `Against ${orig?.invoice_number ?? "the original invoice"}. Saved as a draft; you send it from the next screen.` : "Saved as a draft. You send it from the next screen."} />
      <form onSubmit={submit(false)} noValidate className="space-y-6">
        <Card><CardContent className="grid gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Type" htmlFor="type"><Select id="type" disabled={isNote} {...register("invoice_type")}>
            <option value="sales">Sales invoice</option><option value="purchase">Purchase invoice</option><option value="credit_note">Credit note</option><option value="debit_note">Debit note</option>
          </Select></FormField>
          <FormField label={type === "purchase" ? "Vendor" : "Customer"} htmlFor="party" error={errors.party_id?.message}>
            <Select id="party" disabled={isNote} {...register("party_id")}>
              <option value="">{parties.isLoading ? "Loading…" : "Choose…"}</option>
              {isNote && originalParty.data ? <option value={originalParty.data.id}>{originalParty.data.name} ({originalParty.data.city})</option> : null}
              {parties.data?.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.city})</option>)}
            </Select>
          </FormField>
          <FormField label="Invoice date" htmlFor="date" error={errors.invoice_date?.message}><Input id="date" type="date" max={todayUtc()} {...register("invoice_date")} /></FormField>
          <FormField label="Due date (optional)" htmlFor="due" error={errors.due_date?.message}><Input id="due" type="date" {...register("due_date")} /></FormField>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="h-4 w-4" {...register("is_service")} />This invoice is for services (decides the place of supply)</label>
        </CardContent></Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Line items</CardTitle>
            <div className="flex gap-2">
              <Select aria-label="Add from items" className="w-48" value="" onChange={(e) => addFromItem(e.target.value)}>
                <option value="">Add from items…</option>
                {items.data?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </Select>
              <Button type="button" variant="outline" onClick={() => append({ ...blankLine })}><Plus className="h-4 w-4" />Blank line</Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {errors.line_items?.message ? <p role="alert" className="text-sm text-destructive">{errors.line_items.message}</p> : null}
            {fields.map((field, i) => {
              const e = errors.line_items?.[i];
              const row = preview?.rows[i];
              return (
                <div key={field.id} className="rounded-lg border p-3">
                  <div className="grid gap-3 sm:grid-cols-6">
                    <div className={`${cell} sm:col-span-3`}><Input aria-label="Description" placeholder="Description" {...register(`line_items.${i}.description`)} />{e?.description ? <p className="text-xs text-destructive">{e.description.message}</p> : null}</div>
                    <div className={cell}><Input aria-label="HSN/SAC" placeholder="HSN / SAC" maxLength={8} {...register(`line_items.${i}.hsn_sac_code`)} />{e?.hsn_sac_code ? <p className="text-xs text-destructive">{e.hsn_sac_code.message}</p> : null}</div>
                    <div className={cell}><Input aria-label="Quantity" placeholder="Qty" inputMode="decimal" {...register(`line_items.${i}.quantity`)} />{e?.quantity ? <p className="text-xs text-destructive">{e.quantity.message}</p> : null}</div>
                    <div className={cell}><Input aria-label="Unit" placeholder="Unit" maxLength={10} {...register(`line_items.${i}.unit`)} /></div>
                    <div className={cell}><Input aria-label="Rate" placeholder="Rate ₹" inputMode="decimal" {...register(`line_items.${i}.rate`)} />{e?.rate ? <p className="text-xs text-destructive">{e.rate.message}</p> : null}</div>
                    <div className={cell}><Input aria-label="Discount %" placeholder="Disc %" inputMode="decimal" {...register(`line_items.${i}.discount_percent`)} />{e?.discount_percent ? <p className="text-xs text-destructive">{e.discount_percent.message}</p> : null}</div>
                    <div className={cell}><Select aria-label="GST rate" {...register(`line_items.${i}.gst_rate`)}>{GST_SLABS.map((s) => <option key={s} value={s}>GST {s}%</option>)}</Select></div>
                    <div className={cell}><Input aria-label="Cess %" placeholder="Cess %" inputMode="decimal" {...register(`line_items.${i}.cess_rate`)} />{e?.cess_rate ? <p className="text-xs text-destructive">{e.cess_rate.message}</p> : null}</div>
                    <div className="flex items-center justify-between sm:col-span-2">
                      <span className="text-sm tabular-nums text-muted-foreground">{row ? `Line total ₹${formatINR(toPlain(row.total))}` : ""}</span>
                      {fields.length > 1 ? <Button type="button" size="icon" variant="ghost" aria-label="Remove line" onClick={() => remove(i)}><Trash2 className="h-4 w-4" /></Button> : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card><CardContent className="pt-6"><FormField label="Notes (optional)" htmlFor="notes"><Textarea id="notes" maxLength={2000} {...register("notes")} /></FormField></CardContent></Card>
          <Card><CardContent className="space-y-2 pt-6 text-sm">
            <Row label="Subtotal" value={preview?.subtotal} /><Row label="Discount" value={preview?.discount} /><Row label="Taxable value" value={preview?.taxable} />
            <Row label="GST (CGST + SGST, or IGST)" value={preview?.gst} /><Row label="Cess" value={preview?.cess} />
            <div className="flex justify-between border-t pt-2 text-base font-bold"><span>Grand total</span><span className="tabular-nums">₹{preview ? formatINR(toPlain(preview.grand)) : "0.00"}</span></div>
            <p className="text-xs text-muted-foreground">A preview. The server recalculates every line and splits CGST/SGST/IGST by place of supply; the final figures appear on the draft.</p>
          </CardContent></Card>
        </div>

        {duplicateWarning ? (
          <div role="alert" className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
            <p className="font-medium">Possible duplicate</p><p>{duplicateWarning}</p>
            <Button type="button" className="mt-2" variant="outline" onClick={submit(true)}>It is a different invoice, create anyway</Button>
          </div>
        ) : null}
        {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{serverError}</p> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => navigate("/invoices")}>Cancel</Button>
          <Button type="submit" disabled={isSubmitting || create.isPending}>{create.isPending ? "Saving…" : "Save draft"}</Button>
        </div>
      </form>
    </div>
  );
}

function previewOf(lines: Values["line_items"]) {
  try {
    const ready = lines.filter((l) => l.rate && l.quantity);
    return ready.length ? calcInvoice(ready, false) : null;
  } catch { return null; }
}

function Row({ label, value }: { label: string; value?: bigint }) {
  return <div className="flex justify-between"><span className="text-muted-foreground">{label}</span><span className="tabular-nums">₹{value !== undefined ? formatINR(toPlain(value)) : "0.00"}</span></div>;
}
