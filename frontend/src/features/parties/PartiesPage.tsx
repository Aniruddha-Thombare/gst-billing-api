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
import { stateName } from "@/lib/states";
import { PartyFormDialog } from "./PartyFormDialog";
import { useTogglePartyActive, type Party } from "./partyApi";

export function PartiesPage() {
  const canWrite = useCanWrite();
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [active, setActive] = useState("true");
  const [editing, setEditing] = useState<Party | null>(null);
  const [open, setOpen] = useState(false);
  const toggle = useTogglePartyActive();
  const debouncedName = useDebounced(name, 300); // wait for a pause in typing, so we don't call the API on every key
  const list = usePagedList<Party>("parties", "/parties", { name: debouncedName, party_type: type, is_active: active });

  const openForm = (p: Party | null) => { setEditing(p); setOpen(true); };

  return (
    <div>
      <PageHeader title="Clients" subtitle="Customers and vendors" actions={canWrite ? <Button onClick={() => openForm(null)}><Plus className="h-4 w-4" />New party</Button> : null} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input className="w-full sm:w-64" placeholder="Search name starts with…" value={name} onChange={(e) => setName(e.target.value)} />
        <Select className="w-40" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option><option value="customer">Customers</option><option value="vendor">Vendors</option>
        </Select>
        <Select className="w-40" value={active} onChange={(e) => setActive(e.target.value)}>
          <option value="true">Active</option><option value="false">Inactive</option><option value="">All</option>
        </Select>
      </div>
      <Card className="overflow-x-auto">
        <Table>
          <THead><TR><TH>Name</TH><TH>Type</TH><TH>GSTIN</TH><TH>State</TH><TH>Status</TH>{canWrite ? <TH className="text-right">Actions</TH> : null}</TR></THead>
          <TBody>
            {list.isLoading ? Array.from({ length: 5 }).map((_, i) => <TR key={i}><TD colSpan={6}><Skeleton className="h-5 w-full" /></TD></TR>) : null}
            {list.isError ? <TR><TD colSpan={6} className="text-destructive">{errorMessage(list.error)}</TD></TR> : null}
            {!list.isLoading && !list.isError && list.rows.length === 0 ? <TR><TD colSpan={6} className="py-8 text-center text-muted-foreground">No parties found.</TD></TR> : null}
            {list.rows.map((p) => (
              <TR key={p.id}>
                <TD className="font-medium">{p.name}<div className="text-xs text-muted-foreground">{p.city}</div></TD>
                <TD className="capitalize">{p.party_type}</TD>
                <TD className="font-mono text-xs">{p.gstin ?? <span className="text-muted-foreground">Unregistered</span>}</TD>
                <TD>{stateName(p.state_code)}</TD>
                <TD><StatusBadge status={p.is_active ? "active" : "inactive"} /></TD>
                {canWrite ? (
                  <TD className="space-x-2 text-right">
                    <Button size="sm" variant="outline" onClick={() => openForm(p)}>Edit</Button>
                    <Button size="sm" variant="ghost" disabled={toggle.isPending}
                      onClick={() => toggle.mutate(p, { onError: (e) => toast.error(errorMessage(e)) })}>
                      {p.is_active ? "Deactivate" : "Activate"}
                    </Button>
                  </TD>
                ) : null}
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      {list.hasNextPage ? <div className="mt-4 text-center"><Button variant="outline" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>{list.isFetchingNextPage ? "Loading…" : "Load more"}</Button></div> : null}
      <PartyFormDialog open={open} onOpenChange={setOpen} party={editing} />
    </div>
  );
}
