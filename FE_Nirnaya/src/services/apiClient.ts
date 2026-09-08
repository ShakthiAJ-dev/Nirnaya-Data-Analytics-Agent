/**
 * src/services/apiClient.ts
 * --------------------------
 * Typed HTTP client for the Nirnaya BE (FastAPI).
 *
 * All requests automatically inject:
 *   • Authorization: Bearer <token>  — from sessionStorage
 *   • Content-Type: application/json
 *
 * Usage:
 *   import { api } from './apiClient';
 *   const data = await api.post<SessionInitResponse>('/session/init');
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

const TOKEN_KEY = 'nirnaya_session_token';
const SESSION_ID_KEY = 'nirnaya_session_id';

// ---------------------------------------------------------------------------
// Token storage helpers (sessionStorage — wiped when tab closes)
// ---------------------------------------------------------------------------

export const tokenStore = {
  getToken: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  setToken: (token: string): void => sessionStorage.setItem(TOKEN_KEY, token),
  clearToken: (): void => sessionStorage.removeItem(TOKEN_KEY),

  getSessionId: (): string | null => sessionStorage.getItem(SESSION_ID_KEY),
  setSessionId: (id: string): void => sessionStorage.setItem(SESSION_ID_KEY, id),
  clearSessionId: (): void => sessionStorage.removeItem(SESSION_ID_KEY),

  clear: (): void => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(SESSION_ID_KEY);
  },
};

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  body?: unknown;
  /** Skip injecting the Bearer token (e.g. for /session/init) */
  skipAuth?: boolean;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, skipAuth = false } = opts;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (!skipAuth) {
    const token = tokenStore.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Parse response (always try JSON)
  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }

  if (!res.ok) {
    const err = payload as { error?: { code?: string; message?: string }; detail?: string };
    const code = err?.error?.code ?? 'UNKNOWN';
    const message =
      err?.error?.message ?? err?.detail ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, code, message);
  }

  return payload as T;
}

// ---------------------------------------------------------------------------
// Public API surface
// ---------------------------------------------------------------------------

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'GET' }),

  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...opts, method: 'POST', body }),
};
