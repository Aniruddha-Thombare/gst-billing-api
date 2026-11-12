import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useCanWrite } from "@/features/auth/AuthContext";
import { useDebounced } from "@/hooks/useDebounced";
import { usePagedList } from "@/hooks/usePagedList";
import { errorMessage } from "@/lib/errors";
import { rupees } from "@/lib/format";
import { ItemFormDialog } from "./ItemFormDialog";
import { useToggleItemActive, type Item } from "./itemApi";

export function ItemsPage() {
  const canWrite = useCanWrite();
  const [prefix, setPrefix] = useState("");
  const [active, setActive] = useState("true");
  const [editing, setEditing] = useState<Item | null>(null);
  const [open, setOpen] = useState(false);
  const toggle = useToggleItemActive();
  const debounced = useDebounced(prefix, 300);
  const list = usePagedList<Item>("items", "/items", { name_prefix: debounced, is_active: active });
  const openForm = (i: Item | null) => { setEditing(i); setOpen(true); };

  return (
    <div>
      <PageHeader title="Products / Items" subtitle="Your price list: picking an item on an invoice fills rate, HSN and GST" actions={canWrite ? <Button onClick={() => openForm(null)}><Plus className="h-4 w-4" />New item</Button> : null} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input className="w-full sm:w-64" placeholder="Search name starts with…" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
        <Select className="w-40" value={active} onChange={(e) => setActive(e.target.value)}>
          <option value="true">Active</option><option value="false">Inactive</option><option value="">All</option>
        </Select>
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead><TR><TH>Name</TH><TH>HSN / SAC</TH><TH>Unit</TH><TH className="text-right">Rate</TH><TH className="text-right">GST</TH><TH>Status</TH>{canWrite ? <TH className="text-right">Actions</TH> : null}</TR></THead>
          <TBody>
            {list.isLoading ? Array.from({ length: 5 }).map((_, i) => <TR key={i}><TD colSpan={7}><Skeleton className="h-5 w-full" /></TD></TR>) : null}
            {list.isError ? <TR><TD colSpan={7} className="text-destructive">{errorMessage(list.error)}</TD></TR> : null}
            {!list.isLoading && !list.isError && list.rows.length === 0 ? <TR><TD colSpan={7} className="py-8 text-center text-muted-foreground">No items found.</TD></TR> : null}
            {list.rows.map((i) => (
              <TR key={i.id}>
                <TD className="font-medium">{i.name}{i.is_service ? <span className="ml-2 text-xs text-muted-foreground">service</span> : null}</TD>
                <TD className="font-mono text-xs">{i.hsn_sac_code ?? "—"}</TD>
                <TD>{i.unit}</TD>
                <TD className="text-right tabular-nums">{rupees(i.rate)}</TD>
                <TD className="text-right tabular-nums">{Number(i.gst_rate)}%</TD>
                <TD><StatusBadge status={i.is_active ? "active" : "inactive"} /></TD>
                {canWrite ? (
                  <TD className="space-x-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => openForm(i)}>Edit</Button>
                    <Button size="sm" variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(i, { onError: (e) => toast.error(errorMessage(e)) })}>{i.is_active ? "Deactivate" : "Activate"}</Button>
                  </TD>
                ) : null}
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      {list.hasNextPage ? <div className="mt-4 text-center"><Button variant="outline" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{list.isFetchingNextPage ? "Loading…" : "Load more"}</Button></div> : null}
      <ItemFormDialog open={open} onOpenChange={setOpen} item={editing} />
    </div>
  );
}
