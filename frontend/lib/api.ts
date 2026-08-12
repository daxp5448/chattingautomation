// Same-origin, proxied to the backend by next.config.mjs's rewrite -- this is what lets
// the backend's httpOnly auth cookies work without any cross-site cookie complications.
const API_BASE_URL = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  // Multiple components can hit a 401 around the same moment (e.g. several widgets
  // fetching on the same page); coalesce into a single refresh call instead of a burst
  // of concurrent /auth/refresh requests all racing each other.
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}, _retried = false): Promise<T> {
  // A FormData body (file uploads -- see ImageUploadWidget) must NOT get an explicit
  // Content-Type here: the browser computes its own `multipart/form-data; boundary=...`
  // value when it serializes the body, and setting a plain "application/json" header
  // instead (this function's default for every other call) would corrupt the request.
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers as Record<string, string> | undefined),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers, credentials: "include" });

  if (response.status === 401 && !_retried && path !== "/auth/login" && path !== "/auth/refresh") {
    // Session cookie's access token is expired but the refresh cookie may still be good
    // -- refresh once and silently retry, so a long-idle tab doesn't just show a raw
    // error the moment its access token's 8-hour window closes.
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiFetch<T>(path, options, true);
    }
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
