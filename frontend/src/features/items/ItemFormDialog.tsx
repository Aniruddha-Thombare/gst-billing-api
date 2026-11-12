import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { errorMessage } from "@/lib/errors";
import { GST_SLABS } from "@/lib/states";
import { useSaveItem, type Item } from "./itemApi";

const schema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(200),
  hsn_sac_code: z.string().trim().regex(/^\d{6,8}$|^\d{2}$|^\d{4}$/, "2, 4, 6 or 8 digits").or(z.literal("")),
  unit: z.string().trim().min(1, "Enter a unit").max(10),
  rate: z.string().trim().regex(/^\d{1,15}(\.\d{1,2})?$/, "A positive amount, up to 2 decimals"),
  gst_rate: z.string().refine((v) => GST_SLABS.includes(v), "Choose a GST slab"),
  cess_rate: z.string().trim().regex(/^\d{1,3}(\.\d{1,2})?$/, "A number like 0 or 12.5"),
  is_service: z.boolean(),
});
type Values = z.infer<typeof schema>;
const blank: Values = { name: "", hsn_sac_code: "", unit: "NOS", rate: "", gst_rate: "18", cess_rate: "0", is_service: false };

export function ItemFormDialog({ open, onOpenChange, item }: { open: boolean; onOpenChange: (o: boolean) => void; item: Item | null }) {
  const save = useSaveItem(item?.id);
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: blank });

  useEffect(() => {
    if (!open) return;
    setServerError(null);
    // The API returns "18.00"; normalise to "18" so it matches a slab option exactly.
    const slab = (v: string) => GST_SLABS.find((s) => Number(s) === Number(v)) ?? v;
    reset(item ? { name: item.name, hsn_sac_code: item.hsn_sac_code ?? "", unit: item.unit, rate: item.rate, gst_rate: slab(item.gst_rate), cess_rate: item.cess_rate, is_service: item.is_service } : blank);
  }, [open, item, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    try {
      await save.mutateAsync({ ...v, hsn_sac_code: v.hsn_sac_code || null });
      toast.success(item ? "Item updated" : "Item created");
      onOpenChange(false);
    } catch (e) { setServerError(errorMessage(e)); }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>{item ? "Edit item" : "New item"}</DialogTitle></DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2" noValidate>
          <div className="sm:col-span-2"><FormField label="Name" htmlFor="i-name" error={errors.name?.message}><Input id="i-name" {...register("name")} /></FormField></div>
          <FormField label="HSN / SAC code" htmlFor="i-hsn" error={errors.hsn_sac_code?.message} hint="Your turnover decides the minimum digits; the server checks it on invoices">
            <Input id="i-hsn" maxLength={8} {...register("hsn_sac_code")} />
          </FormField>
          <FormField label="Unit" htmlFor="i-unit" error={errors.unit?.message}><Input id="i-unit" maxLength={10} {...register("unit")} /></FormField>
          <FormField label="Rate (₹)" htmlFor="i-rate" error={errors.rate?.message}><Input id="i-rate" inputMode="decimal" {...register("rate")} /></FormField>
          <FormField label="GST rate (%)" htmlFor="i-gst" error={errors.gst_rate?.message}>
            <Select id="i-gst" {...register("gst_rate")}>{GST_SLABS.map((s) => <option key={s} value={s}>{s}%</option>)}</Select>
          </FormField>
          <FormField label="Cess (%)" htmlFor="i-cess" error={errors.cess_rate?.message}><Input id="i-cess" inputMode="decimal" {...register("cess_rate")} /></FormField>
          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" className="h-4 w-4" {...register("is_service")} />This is a service (SAC code)</label>
          {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive sm:col-span-2">{serverError}</p> : null}
          <div className="flex justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
