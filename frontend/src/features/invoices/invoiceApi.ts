import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http, idempotent } from "@/lib/api";

/** All money fields are strings from the API ("1180.00"). Never Number() them. */
export interface InvoiceSummary {
  id: string; invoice_number: string; invoice_type: string; invoice_date: string; due_date: string | null;
  party_id: string; party_name: string | null; party_gstin: string | null; total_amount: string; paid_amount: string;
  outstanding_amount: string; refund_due_amount: string; invoice_status: string; created_at: string;
}
export interface LineItem {
  id: string; line_number: number; description: string; hsn_sac_code: string | null; quantity: string; unit: string | null;
  rate: string; discount_percent: string; discount_amount: string; taxable_amount: string; gst_rate: string;
  cgst_rate: string; sgst_rate: string; igst_rate: string; cgst_amount: string; sgst_amount: string; igst_amount: string;
  cess_rate: string; cess_amount: string; total_amount: string;
}
export interface Invoice extends Omit<InvoiceSummary, "party_name"> {
  tenant_id: string; financial_year: string; party_state_code: string; supply_type: string; place_of_supply: string;
  reverse_charge: boolean; subtotal: string; discount_amount: string; taxable_amount: string; cgst_amount: string;
  sgst_amount: string; igst_amount: string; cess_amount: string; credited_amount: string; refunded_amount: string;
  notes: string | null; terms: string | null; original_invoice_id: string | null; is_locked: boolean; voided_at: string | null;
  void_reason: string | null; line_items: LineItem[];
}
export interface Payment {
  id: string; payment_number: string; invoice_id: string; payment_date: string; amount: string; payment_mode: string;
  reference_number: string | null; bank_name: string | null; status: string; created_at: string;
}

const refresh = (qc: ReturnType<typeof useQueryClient>, invoiceId?: string) => {
  qc.invalidateQueries({ queryKey: ["invoices"] });
  if (invoiceId) { qc.invalidateQueries({ queryKey: ["invoice", invoiceId] }); qc.invalidateQueries({ queryKey: ["payments", invoiceId] }); }
  qc.invalidateQueries({ queryKey: ["dashboard"] });
};

export const useInvoice = (id: string) =>
  useQuery({ queryKey: ["invoice", id], queryFn: async () => (await http.get<Invoice>(`/invoices/${id}`)).data });

export const useInvoicePayments = (id: string) =>
  useQuery({ queryKey: ["payments", id], queryFn: async () => (await http.get<{ items: Payment[] }>("/payments", { params: { invoice_id: id, limit: 100 } })).data.items });

export function useCreateInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, key }: { body: Record<string, unknown>; key: string }) =>
      (await http.post<Invoice>("/invoices/create_invoice", body, idempotent(key))).data,
    onSuccess: () => refresh(qc),
  });
}

export function useSendInvoice(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (key: string) => (await http.post<Invoice>(`/invoices/${id}/send`, undefined, idempotent(key))).data,
    onSuccess: () => refresh(qc, id),
  });
}

export function useVoidInvoice(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (void_reason: string) => (await http.post<Invoice>(`/invoices/${id}/void`, { void_reason })).data,
    onSuccess: () => refresh(qc, id),
  });
}

export function useRecordPayment(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, key }: { body: Record<string, unknown>; key: string }) =>
      (await http.post(`/invoices/${id}/payments`, body, idempotent(key))).data,
    onSuccess: () => refresh(qc, id),
  });
}

export function useCancelPayment(invoiceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ paymentId, reason }: { paymentId: string; reason: string }) =>
      (await http.post(`/payments/${paymentId}/cancel`, { cancellation_reason: reason })).data,
    onSuccess: () => refresh(qc, invoiceId),
  });
}

export interface Refund {
  id: string; refund_number: string; invoice_id: string; refund_date: string; amount: string; refund_mode: string;
  reference_number: string | null; bank_name: string | null; status: string; created_at: string;
}

export const useInvoiceRefunds = (id: string) =>
  useQuery({ queryKey: ["refunds", id], queryFn: async () => (await http.get<Refund[]>(`/invoices/${id}/refunds`)).data });

export function useRecordRefund(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, key }: { body: Record<string, unknown>; key: string }) =>
      (await http.post(`/invoices/${id}/refunds`, body, idempotent(key))).data,
    onSuccess: () => { refresh(qc, id); qc.invalidateQueries({ queryKey: ["refunds", id] }); },
  });
}

export function useCancelRefund(invoiceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ refundId, reason }: { refundId: string; reason: string }) =>
      (await http.post(`/refunds/${refundId}/cancel`, { cancellation_reason: reason })).data,
    onSuccess: () => { refresh(qc, invoiceId); qc.invalidateQueries({ queryKey: ["refunds", invoiceId] }); },
  });
}
