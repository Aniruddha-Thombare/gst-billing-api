import axios from "axios";

/** Our backend always answers errors as {"error": {"code", "message", "details?"}}. */
export interface FieldDetail { loc: string[]; message: string; type: string; }

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: FieldDetail[] | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn anything thrown (axios error, ApiError, plain Error) into a message for the user. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = error.details?.length
      ? " — " + error.details.map((d) => `${d.loc.slice(1).join(".")}: ${d.message}`).join("; ")
      : "";
    return `${error.message}${fields}`;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Is the backend running?");
    }
    const body = error.response.data as { error?: { code: string; message: string; details?: FieldDetail[] } } | undefined;
    if (body?.error) return new ApiError(error.response.status, body.error.code, body.error.message, body.error.details ?? null);
    return new ApiError(error.response.status, `HTTP_${error.response.status}`, error.message);
  }
  return new ApiError(0, "UNKNOWN", error instanceof Error ? error.message : "Unknown error");
}
