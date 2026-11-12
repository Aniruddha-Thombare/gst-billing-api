import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { http } from "@/lib/api";
import { readCurrentUser, tokens, type CurrentUser } from "@/lib/tokens";

interface AuthValue {
  user: CurrentUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<CurrentUser | null>(() => readCurrentUser());

  const login = useCallback(async (email: string, password: string) => {
    // POST /auth/login -> {access_token, refresh_token}. The error envelope becomes an ApiError via the interceptor.
    const res = await http.post("/auth/login", { email, password });
    tokens.save(res.data.access_token, res.data.refresh_token);
    queryClient.clear();               // never show the previous user's cached data
    setUser(readCurrentUser());
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      if (tokens.refresh) await http.post("/auth/logout", { refresh_token: tokens.refresh });
    } catch { /* logging out must always succeed locally */ }
    tokens.clear();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Roles that may create or change data. The server enforces this; the UI uses it to hide buttons. */
export function useCanWrite(): boolean {
  const { user } = useAuth();
  return user?.role === "owner" || user?.role === "accountant";
}
