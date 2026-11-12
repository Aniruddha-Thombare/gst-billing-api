import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { http } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

const schema = z.object({
  current_password: z.string().min(1, "Enter your current password"),
  new_password: z.string().min(8, "At least 8 characters").max(72).refine((v) => /[A-Za-z]/.test(v) && /\d/.test(v), "Needs a letter and a digit"),
});
type Values = z.infer<typeof schema>;

export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });
  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    try { await http.post("/users/me/password", v); toast.success("Password changed"); reset(); onOpenChange(false); } catch (e) { setServerError(errorMessage(e)); }
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-w-sm">
      <DialogHeader><DialogTitle>Change password</DialogTitle></DialogHeader>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <FormField label="Current password" htmlFor="cp-cur" error={errors.current_password?.message}><Input id="cp-cur" type="password" autoComplete="current-password" {...register("current_password")} /></FormField>
        <FormField label="New password" htmlFor="cp-new" error={errors.new_password?.message}><Input id="cp-new" type="password" autoComplete="new-password" {...register("new_password")} /></FormField>
        {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">{serverError}</p> : null}
        <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" disabled={isSubmitting}>Change password</Button></div>
      </form>
    </DialogContent></Dialog>
  );
}
