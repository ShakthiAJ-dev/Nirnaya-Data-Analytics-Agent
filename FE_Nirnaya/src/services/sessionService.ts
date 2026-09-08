/**
 * src/services/sessionService.ts
 * --------------------------------
 * Session lifecycle: init, LLM key submission, teardown.
 *
 * Session init flow:
 *   1. Check sessionStorage — if a valid token already exists, reuse it.
 *   2. POST /session/init → { session_id, token, expires_in }
 *   3. Persist token + session_id to sessionStorage.
 *
 * LLM Key flow:
 *   1. POST /session/llm-provider-key { provider, api_key }
 *      → BE validates key against provider (live round-trip) then encrypts
 *        and stores in Redis for the session lifetime.
 *
 * The token is automatically injected by apiClient on every subsequent call.
 */

import { api, tokenStore } from './apiClient';

// ---------------------------------------------------------------------------
// Types (mirror the BE schemas)
// ---------------------------------------------------------------------------

export interface SessionInitResponse {
  session_id: string;
  token: string;
  expires_in: number; // seconds
}

export interface LLMKeySubmitRequest {
  provider: 'openai' | 'anthropic';
  api_key: string;
}

export interface LLMKeySubmitResponse {
  status: 'stored';
}

/** A single model entry returned by GET /session/models */
export interface BackendModel {
  id: string;
  name: string;
  provider: 'anthropic' | 'openai';
  description: string;
}

export interface AvailableModelsResponse {
  models: BackendModel[];
}

export interface SessionState {
  sessionId: string;
  token: string;
  /** Unix timestamp (ms) when the token was issued */
  issuedAt: number;
  /** Seconds until expiry (from BE) */
  expiresIn: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SESSION_STATE_KEY = 'nirnaya_session_state_v1';

// ---------------------------------------------------------------------------
// Persistence helpers (sessionStorage)
// ---------------------------------------------------------------------------

function saveState(state: SessionState): void {
  tokenStore.setToken(state.token);
  tokenStore.setSessionId(state.sessionId);
  sessionStorage.setItem(SESSION_STATE_KEY, JSON.stringify(state));
}

function loadState(): SessionState | null {
  const raw = sessionStorage.getItem(SESSION_STATE_KEY);
  if (!raw) return null;
  try {
    const state: SessionState = JSON.parse(raw);
    // Check if token is still alive (client-side best-effort check)
    const elapsedSeconds = (Date.now() - state.issuedAt) / 1000;
    if (elapsedSeconds >= state.expiresIn) {
      clearState();
      return null;
    }
    return state;
  } catch {
    return null;
  }
}

function clearState(): void {
  tokenStore.clear();
  sessionStorage.removeItem(SESSION_STATE_KEY);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Ensure a valid session exists.
 *
 * - If a non-expired token is already in sessionStorage, returns it immediately.
 * - Otherwise calls POST /session/init and stores the new token.
 *
 * Safe to call multiple times — only one network call is made per tab lifecycle.
 */
export async function initSession(): Promise<SessionState> {
  // Reuse existing valid session
  const existing = loadState();
  if (existing) {
    console.debug('[session] Reusing existing session:', existing.sessionId);
    return existing;
  }

  console.debug('[session] Creating new session...');
  const resp = await api.post<SessionInitResponse>(
    '/session/init',
    undefined,
    { skipAuth: true }, // No token needed for init
  );

  const state: SessionState = {
    sessionId: resp.session_id,
    token: resp.token,
    issuedAt: Date.now(),
    expiresIn: resp.expires_in,
  };

  saveState(state);
  console.debug('[session] Session created:', state.sessionId);
  return state;
}

/**
 * Submit an LLM API key to the BE for the current session.
 *
 * The BE will:
 *   1. Validate the key format (regex)
 *   2. Make a live round-trip to the provider to confirm it works
 *   3. AES-256-GCM encrypt and store in Redis for the session lifetime
 *   4. Return { status: 'stored' } — the key is never echoed back
 *
 * Throws ApiError with a user-friendly message on validation failure.
 */
export async function submitLLMKey(
  provider: 'openai' | 'anthropic',
  apiKey: string,
): Promise<void> {
  if (!apiKey.trim()) return; // Skip empty keys silently

  const body: LLMKeySubmitRequest = {
    provider,
    api_key: apiKey,
  };

  await api.post<LLMKeySubmitResponse>('/session/llm-provider-key', body);
  console.debug('[session] LLM key stored for provider:', provider);
}

/**
 * Get the current session state without creating a new one.
 * Returns null if no session exists.
 */
export function getSession(): SessionState | null {
  return loadState();
}

/**
 * Clear the current session from storage.
 * The BE session will expire naturally via Redis TTL.
 */
export function clearSession(): void {
  clearState();
  console.debug('[session] Session cleared from storage');
}

/**
 * Fetch the list of models available for the current session from the BE.
 *
 * The BE returns only models whose provider keys are stored in Redis
 * (i.e. keys the user has already submitted and validated).
 * Returns an empty array if the session doesn't exist yet or has no keys.
 *
 * Call this:
 *   • Once after session init (to show pre-configured keys from a resumed session)
 *   • Again after the user saves new credentials in the modal
 */
export async function fetchAvailableModels(): Promise<BackendModel[]> {
  const session = loadState();
  if (!session) {
    // No active session — cannot call authenticated endpoint
    return [];
  }

  try {
    const resp = await api.get<AvailableModelsResponse>('/session/models');
    console.debug('[session] Available models fetched:', resp.models.length);
    return resp.models;
  } catch (err) {
    console.warn('[session] fetchAvailableModels failed:', err);
    return [];
  }
}

