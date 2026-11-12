import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { http } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

// Same rules as the backend's TenantRegisterRequest, so most mistakes are caught before the request.
const schema = z
  .object({
    business_name: z.string().trim().min(2, "At least 2 characters").max(255),
    legal_name: z.string().trim().min(2, "At least 2 characters").max(255),
    gstin: z.string().trim().toUpperCase().regex(/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/, "Not a valid 15-character GSTIN"),
    address_line: z.string().trim().min(5, "At least 5 characters").max(500),
    city: z.string().trim().min(2, "Enter the city").max(100),
    pincode: z.string().trim().regex(/^[1-9][0-9]{5}$/, "6 digits, not starting with 0"),
    state_code: z.string().trim().regex(/^[0-9]{2}$/, "2 digits, for example 27"),
    full_name: z.string().trim().min(1, "Enter your name").max(255),
    email: z.string().trim().email("Enter a valid email"),
    password: z.string().min(8, "At least 8 characters").max(72, "At most 72 characters"),
  })
  // A cross-field rule: the first two digits of a GSTIN ARE the state code.
  .refine((v) => v.gstin.slice(0, 2) === v.state_code, { path: ["state_code"], message: "Must equal the first 2 digits of the GSTIN" });
type FormValues = z.infer<typeof schema>;

export function RegisterPage() {
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      const res = await http.post("/auth/register", { ...values, registration_type: "regular" });
      toast.success(res.data.message ?? "Registered. Log in to continue.");
      navigate("/login");
    } catch (error) {
      setServerError(errorMessage(error));
    }
  });

  const text = (id: keyof FormValues, label: string, extra: { type?: string; hint?: string; maxLength?: number; placeholder?: string; autoComplete?: string } = {}) => (
    <FormField label={label} htmlFor={id} error={errors[id]?.message} hint={extra.hint}>
      <Input id={id} type={extra.type} maxLength={extra.maxLength} placeholder={extra.placeholder} autoComplete={extra.autoComplete} {...register(id)} />
    </FormField>
  );

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-2xl">
        <CardHeader className="pb-4"><CardTitle className="text-xl">Register your business</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2" noValidate>
            {text("business_name", "Business name")}
            {text("legal_name", "Legal name")}
            {text("gstin", "GSTIN", { maxLength: 15, placeholder: "27AAPFU0939F1ZV" })}
            {text("state_code", "State code", { maxLength: 2, placeholder: "27", hint: "First 2 digits of the GSTIN" })}
            <div className="sm:col-span-2">{text("address_line", "Address")}</div>
            {text("city", "City")}
            {text("pincode", "Pincode", { maxLength: 6 })}
            {text("full_name", "Your name")}
            {text("email", "Email", { type: "email", autoComplete: "username" })}
            <div className="sm:col-span-2">{text("password", "Password", { type: "password", autoComplete: "new-password", hint: "8 to 72 characters" })}</div>
            {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive sm:col-span-2">{serverError}</p> : null}
            <div className="sm:col-span-2">
              <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting ? "Registering…" : "Register"}</Button>
              <p className="mt-3 text-center text-sm text-muted-foreground">Already registered? <Link className="text-primary hover:underline" to="/login">Log in</Link></p>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
