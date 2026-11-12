import { Badge, type BadgeProps } from "@/components/ui/badge";

const VARIANTS: Record<string, BadgeProps["variant"]> = {
  paid: "success", sent: "info", partial: "info", draft: "warning", overdue: "destructive", void: "destructive",
  cancelled: "destructive", active: "success", inactive: "default",
};

/** One place decides which colour each status gets. */
export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={VARIANTS[status] ?? "default"} className="capitalize">{status.replace("_", " ")}</Badge>;
}
