import axios, { type AxiosRequestConfig } from "axios";
import { toApiError } from "./errors";
import { tokens } from "./tokens";

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

/** One axios instance for the whole app: base URL + JSON handling live here. */
export const http = axios.create({ baseURL: `${API_URL}/api/v1`, timeout: 30_000 });

// REQUEST interceptor: runs before every request leaves the browser.
http.interceptors.request.use((config) => {
  const access = tokens.access;
  if (access && !config.headers.has("Authorization")) config.headers.set("Authorization", `Bearer ${access}`);
  return config;
});

// RESPONSE interceptor: if the access token expired, get a new one ONCE and replay the request.
let refreshing: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (!tokens.refresh) return false;
  refreshing ??= axios
    .post(`${API_URL}/api/v1/auth/refresh`, { refresh_token: tokens.refresh })
    .then((res) => { tokens.save(res.data.access_token); return true; })
    .catch(() => false)
    .finally(() => { refreshing = null; });   // several expired requests share ONE refresh call
  return refreshing;
}

type Retriable = AxiosRequestConfig & { _retried?: boolean };

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const apiError = toApiError(error);
    const original = error.config as Retriable | undefined;
    if (apiError.status === 401 && original && !original._retried && !original.url?.includes("/auth/")) {
      if (apiError.code === "TOKEN_EXPIRED" && (await refreshAccessToken())) {
        original._retried = true;
        original.headers = { ...original.headers, Authorization: `Bearer ${tokens.access}` } as never;
        return http(original);
      }
      tokens.clear();
      window.location.assign("/login");
    }
    return Promise.reject(apiError);
  },
);

/** A fresh Idempotency-Key. Create ONE per form submission attempt and reuse it on retry. */
export const newIdempotencyKey = () => crypto.randomUUID();

export const idempotent = (key: string): AxiosRequestConfig => ({ headers: { "Idempotency-Key": key } });

/** Download a PDF (needs the Authorization header, so a plain link cannot be used) and open it in a new tab. */
export async function openPdf(path: string): Promise<void> {
  const res = await http.get<Blob>(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export interface Page<T> { items: T[]; next_cursor: string | null; }

/** Download a file (CSV etc.) that needs the Authorization header: fetch as a blob, then click a temporary link. */
export async function downloadFile(path: string, params: Record<string, string>, filename: string): Promise<void> {
  const res = await http.get<Blob>(path, { params, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
