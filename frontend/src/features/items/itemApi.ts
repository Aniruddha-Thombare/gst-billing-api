import { useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/lib/api";

/** Money fields arrive as strings ("500.00") and stay strings: never Number()/parseFloat on money. */
export interface Item {
  id: string; name: string; hsn_sac_code: string | null; unit: string; rate: string; gst_rate: string; cess_rate: string;
  is_service: boolean; is_active: boolean; created_at: string;
}

export function useSaveItem(editingId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      editingId ? (await http.put<Item>(`/items/${editingId}`, body)).data : (await http.post<Item>("/items", body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["items"] }),
  });
}

export function useToggleItemActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (i: Item) => (await http.post<Item>(`/items/${i.id}/${i.is_active ? "deactivate" : "activate"}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["items"] }),
  });
}
