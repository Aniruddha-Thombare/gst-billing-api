import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useAuth } from "@/features/auth/AuthContext";
import { http } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

interface UserRow { id: string; email: string; full_name: string; role: string; is_active: boolean; }
const ROLES = ["accountant", "viewer", "auditor"];
const ROLE_HELP: Record<string, string> = { accountant: "Can create and edit everything except users", viewer: "Read-only, including the dashboard", auditor: "Read-only for audit; no dashboard" };

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter a name").max(150),
  email: z.string().trim().email("Enter a valid email"),
  password: z.string().min(8, "At least 8 characters").max(72).refine((v) => /[A-Za-z]/.test(v) && /\d/.test(v), "Needs a letter and a digit"),
  role: z.enum(["accountant", "viewer", "auditor"]),
});
type Values = z.infer<typeof schema>;

export function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const users = useQuery({ queryKey: ["users"], queryFn: async () => (await http.get<UserRow[]>("/users")).data });
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const create = useMutation({ mutationFn: async (v: Values) => (await http.post("/users", v)).data, onSuccess: refresh });
  const toggle = useMutation({ mutationFn: async (u: UserRow) => (await http.post(`/users/${u.id}/${u.is_active ? "deactivate" : "activate"}`)).data, onSuccess: refresh });
  const setRole = useMutation({ mutationFn: async ({ id, role }: { id: string; role: string }) => (await http.patch(`/users/${id}/role`, { role })).data, onSuccess: refresh });
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { role: "accountant", full_name: "", email: "", password: "" } });

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    try { await create.mutateAsync(v); toast.success("User created"); reset(); setOpen(false); } catch (e) { setServerError(errorMessage(e)); }
  });

  return (
    <div>
      <PageHeader title="Users & Roles" subtitle="Owner only" actions={<Button onClick={() => { setServerError(null); setOpen(true); }}><Plus className="h-4 w-4" />New user</Button>} />
      {users.isError ? <p role="alert" className="text-destructive">{errorMessage(users.error)}</p> : null}
      <Card className="overflow-x-auto"><Table>
        <THead><TR><TH>Name</TH><TH>Email</TH><TH>Role</TH><TH>Status</TH><TH className="text-right">Actions</TH></TR></THead>
        <TBody>
          {users.data?.map((u) => {
            const isOwner = u.role === "owner"; const isMe = u.id === me?.userId;
            return (
              <TR key={u.id}>
                <TD className="font-medium">{u.full_name}{isMe ? <span className="ml-2 text-xs text-muted-foreground">(you)</span> : null}</TD><TD>{u.email}</TD>
                <TD>{isOwner ? <span className="capitalize">owner</span> : (
                  <Select className="w-36" value={u.role} aria-label={`Role of ${u.full_name}`} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value }, { onSuccess: () => toast.success("Role updated"), onError: (err) => toast.error(errorMessage(err)) })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</Select>)}</TD>
                <TD><StatusBadge status={u.is_active ? "active" : "inactive"} /></TD>
                <TD className="text-right">{isOwner || isMe ? null : <Button size="sm" variant="ghost" onClick={() => toggle.mutate(u, { onError: (err) => toast.error(errorMessage(err)) })}>{u.is_active ? "Deactivate" : "Activate"}</Button>}</TD>
              </TR>);
          })}
        </TBody>
      </Table></Card>
      <p className="mt-3 text-xs text-muted-foreground">A deactivated user cannot log in again. Their existing 15-minute token keeps working until it expires.</p>

      <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>New user</DialogTitle></DialogHeader>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <FormField label="Full name" htmlFor="u-name" error={errors.full_name?.message}><Input id="u-name" {...register("full_name")} /></FormField>
          <FormField label="Email" htmlFor="u-email" error={errors.email?.message}><Input id="u-email" type="email" {...register("email")} /></FormField>
          <FormField label="Temporary password" htmlFor="u-pass" error={errors.password?.message} hint="8 to 72 characters, with a letter and a digit"><Input id="u-pass" type="password" autoComplete="new-password" {...register("password")} /></FormField>
          <FormField label="Role" htmlFor="u-role" hint={ROLE_HELP[watch("role")]}><Select id="u-role" {...register("role")}>{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</Select></FormField>
          {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">{serverError}</p> : null}
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create user"}</Button></div>
        </form>
      </DialogContent></Dialog>
    </div>
  );
}
