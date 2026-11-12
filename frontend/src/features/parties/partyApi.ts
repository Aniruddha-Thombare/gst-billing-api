import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/lib/api";

export interface Party {
  id: string; name: string; gstin: string | null; pan: string | null; address_line1: string; address_line2: string | null;
  city: string; pincode: string; state_code: string; email: string | null; phone: string | null;
  party_type: "customer" | "vendor"; is_active: boolean; created_at: string; updated_at: string;
}
export type PartyInput = Omit<Party, "id" | "is_active" | "created_at" | "updated_at" | "party_type"> & { party_type?: "customer" | "vendor" };

export function useSaveParty(editingId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      editingId ? (await http.put<Party>(`/parties/${editingId}`, body)).data : (await http.post<Party>("/parties", body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["parties"] }),
  });
}

export function useTogglePartyActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (p: Party) => (await http.post<Party>(`/parties/${p.id}/${p.is_active ? "deactivate" : "activate"}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["parties"] }),
  });
}
