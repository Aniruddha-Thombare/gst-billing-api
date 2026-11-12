import { useRef } from "react";
import { newIdempotencyKey } from "@/lib/api";

/**
 * One Idempotency-Key per *intent*. Retrying the SAME request (timeout, double-click) must reuse the key,
 * so the server replays the first result instead of creating a second invoice/payment.
 * If the payload changes (the user edited the form), it is a different request, so a new key is created.
 */
export function useIdempotencyKey() {
  const state = useRef<{ key: string; fingerprint: string } | null>(null);
  return {
    keyFor(payload: unknown): string {
      const fingerprint = JSON.stringify(payload);
      if (!state.current || state.current.fingerprint !== fingerprint) state.current = { key: newIdempotencyKey(), fingerprint };
      return state.current.key;
    },
    reset() { state.current = null; },
  };
}
