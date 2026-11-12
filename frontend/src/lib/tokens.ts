/**
 * Where the login tokens live. sessionStorage is wiped when the tab closes.
 * Trade-off to know for interviews: any script on the page can read it (XSS), so we never
 * render server text as HTML. The safer production option is an httpOnly cookie set by the
 * server, which needs backend changes; we note it as a later hardening step.
 */
const ACCESS = "accessToken";
const REFRESH = "refreshToken";

export const tokens = {
  get access() { return sessionStorage.getItem(ACCESS); },
  get refresh() { return sessionStorage.getItem(REFRESH); },
  save(access: string, refresh?: string | null) {
    sessionStorage.setItem(ACCESS, access);
    if (refresh) sessionStorage.setItem(REFRESH, refresh);
  },
  clear() {
    sessionStorage.removeItem(ACCESS);
    sessionStorage.removeItem(REFRESH);
  },
};

export type Role = "owner" | "accountant" | "viewer" | "auditor";
export interface CurrentUser { userId: string; tenantId: string; role: Role; }

/** Reads the role from the JWT payload. Used only to SHOW or HIDE buttons; the server enforces access. */
export function readCurrentUser(): CurrentUser | null {
  const token = tokens.access;
  if (!token) return null;
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(part));
    return { userId: payload.sub, tenantId: payload.tenant_id, role: payload.role };
  } catch {
    return null;
  }
}
