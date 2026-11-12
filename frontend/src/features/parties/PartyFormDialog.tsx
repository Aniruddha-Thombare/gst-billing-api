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
import { STATES } from "@/lib/states";
import { useSaveParty, type Party } from "./partyApi";

const schema = z.object({
  party_type: z.enum(["customer", "vendor"]),
  name: z.string().trim().min(1, "Enter a name").max(255),
  gstin: z.string().trim().toUpperCase().regex(/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/, "Not a valid GSTIN").or(z.literal("")),
  pan: z.string().trim().toUpperCase().regex(/^[A-Z]{5}[0-9]{4}[A-Z]$/, "Not a valid PAN").or(z.literal("")),
  address_line1: z.string().trim().min(1, "Enter the address").max(500),
  address_line2: z.string().trim().max(500),
  city: z.string().trim().min(1, "Enter the city").max(100),
  pincode: z.string().trim().regex(/^[1-9][0-9]{5}$/, "6 digits"),
  state_code: z.string().regex(/^[0-9]{2}$/, "Choose a state"),
  email: z.string().trim().email("Not a valid email").or(z.literal("")),
  phone: z.string().trim().regex(/^[0-9+\-\s]{7,20}$/, "7 to 20 digits").or(z.literal("")),
}).refine((v) => !v.gstin || v.gstin.slice(0, 2) === v.state_code, { path: ["state_code"], message: "State must match the first 2 digits of the GSTIN" });
type Values = z.infer<typeof schema>;

const blank: Values = { party_type: "customer", name: "", gstin: "", pan: "", address_line1: "", address_line2: "", city: "", pincode: "", state_code: "", email: "", phone: "" };

export function PartyFormDialog({ open, onOpenChange, party }: { open: boolean; onOpenChange: (o: boolean) => void; party: Party | null }) {
  const save = useSaveParty(party?.id);
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: blank });

  useEffect(() => {
    if (!open) return;
    setServerError(null);
    reset(party ? {
      party_type: party.party_type, name: party.name, gstin: party.gstin ?? "", pan: party.pan ?? "", address_line1: party.address_line1,
      address_line2: party.address_line2 ?? "", city: party.city, pincode: party.pincode, state_code: party.state_code,
      email: party.email ?? "", phone: party.phone ?? "",
    } : blank);
  }, [open, party, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    // Blank optional fields are sent as null, not "", so the server stores "not provided".
    const body: Record<string, unknown> = {
      ...v, gstin: v.gstin || null, pan: v.pan || null, address_line2: v.address_line2 || null, email: v.email || null, phone: v.phone || null,
    };
    if (party) delete body.party_type; // the type cannot change after creation
    try {
      await save.mutateAsync(body);
      toast.success(party ? "Party updated" : "Party created");
      onOpenChange(false);
    } catch (e) { setServerError(errorMessage(e)); }
  });

  const text = (id: keyof Values, label: string, props: { maxLength?: number; hint?: string; type?: string } = {}) => (
    <FormField label={label} htmlFor={`p-${id}`} error={errors[id]?.message} hint={props.hint}>
      <Input id={`p-${id}`} type={props.type} maxLength={props.maxLength} {...register(id)} />
    </FormField>
  );

  const hasGstin = Boolean(watch("gstin"));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle>{party ? "Edit party" : "New party"}</DialogTitle></DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2" noValidate>
          <FormField label="Type" htmlFor="p-party_type">
            <Select id="p-party_type" disabled={Boolean(party)} {...register("party_type")}>
              <option value="customer">Customer (you sell to them)</option>
              <option value="vendor">Vendor (you buy from them)</option>
            </Select>
          </FormField>
          {text("name", "Name")}
          {text("gstin", "GSTIN", { maxLength: 15, hint: "Leave empty for an unregistered (B2C) customer" })}
          {text("pan", "PAN", { maxLength: 10, hint: hasGstin ? "Taken from the GSTIN" : undefined })}
          <div className="sm:col-span-2">{text("address_line1", "Address line 1")}</div>
          <div className="sm:col-span-2">{text("address_line2", "Address line 2 (optional)")}</div>
          {text("city", "City")}
          {text("pincode", "Pincode", { maxLength: 6 })}
          <FormField label="State" htmlFor="p-state_code" error={errors.state_code?.message}>
            <Select id="p-state_code" {...register("state_code")}>
              <option value="">Choose…</option>
              {STATES.map((s) => <option key={s.code} value={s.code}>{s.code} · {s.name}</option>)}
            </Select>
          </FormField>
          {text("email", "Email (optional)", { type: "email" })}
          {text("phone", "Phone (optional)")}
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
