import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { z } from "zod";
import { FormField } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/errors";
import { useAuth } from "./AuthContext";

// Zod describes the rules once; react-hook-form runs them in the browser BEFORE any request is sent.
const schema = z.object({
  email: z.string().trim().email("Enter a valid email"),
  password: z.string().min(1, "Enter your password").max(72),
});
type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormValues>({ resolver: zodResolver(schema) });

  if (user) return <Navigate to="/" replace />;

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      await login(values.email, values.password);
      navigate("/", { replace: true });
    } catch (error) {
      setServerError(errorMessage(error));        // e.g. "Invalid email or password." or the lockout message
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="pb-4">
          <CardTitle className="text-xl">Log in to GST Billing</CardTitle>
          <p className="text-sm text-muted-foreground">Invoices, payments and GST returns in one place.</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField label="Email" htmlFor="email" error={errors.email?.message}>
              <Input id="email" type="email" autoComplete="username" {...register("email")} />
            </FormField>
            <FormField label="Password" htmlFor="password" error={errors.password?.message}>
              <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
            </FormField>
            {serverError ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">{serverError}</p> : null}
            <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting ? "Logging in…" : "Log in"}</Button>
            <p className="text-center text-sm text-muted-foreground">New business? <Link className="text-primary hover:underline" to="/register">Register</Link></p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
