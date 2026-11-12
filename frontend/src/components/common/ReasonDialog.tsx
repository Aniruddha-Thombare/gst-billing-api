import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/errors";

/** Asks for a mandatory reason (min 5 chars, like the backend) before a destructive action. */
export function ReasonDialog({ open, onOpenChange, title, description, confirmLabel, onConfirm }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description: string; confirmLabel: string;
  onConfirm: (reason: string) => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tooShort = reason.trim().length < 5;

  const submit = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(reason.trim()); setReason(""); onOpenChange(false); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
        <Textarea aria-label="Reason" placeholder="Reason (at least 5 characters)" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        {error ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">{error}</p> : null}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Back</Button>
          <Button variant="destructive" disabled={tooShort || busy} onClick={submit}>{busy ? "Working…" : confirmLabel}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
