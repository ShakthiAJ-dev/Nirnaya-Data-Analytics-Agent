/**
 * src/hooks/useSession.ts
 * ------------------------
 * React hook that manages the full session + WebSocket lifecycle.
 *
 * What it does on mount:
 *   1. Calls initSession() → POST /session/init (skipped if token exists in sessionStorage)
 *   2. Creates a NirnayaWSClient with the token
 *   3. Calls wsClient.connect() → sends auth frame → BE validates
 *   4. Starts ping/pong keepalive (keeps Redis TTL sliding every 30s)
 *
 * On unmount:
 *   → Calls wsClient.disconnect() (sends WS close code 1000)
 *
 * Returns:
 *   • sessionId       — the current session ID (or null while loading)
 *   • wsClient        — the NirnayaWSClient instance (null until connected)
 *   • sessionStatus   — 'idle' | 'loading' | 'ready' | 'error'
 *   • wsStatus        — 'disconnected' | 'connecting' | 'connected' | 'error'
 *   • error           — last error message
 *   • submitKey       — function to POST an LLM key to the BE
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { initSession, submitLLMKey } from '../services/sessionService';
import { NirnayaWSClient } from '../services/wsClient';
import type { WSFrame } from '../services/wsClient';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SessionStatus = 'idle' | 'loading' | 'ready' | 'error';
export type WSStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface UseSessionResult {
  sessionId: string | null;
  wsClient: NirnayaWSClient | null;
  sessionStatus: SessionStatus;
  wsStatus: WSStatus;
  error: string | null;
  /** Submit an LLM provider key to the BE. Throws if validation fails. */
  submitKey: (provider: 'openai' | 'anthropic', apiKey: string) => Promise<void>;
  /** Callback registry: fires when a WS frame arrives */
  onWSMessage: (handler: (frame: WSFrame) => void) => () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSession(): UseSessionResult {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('idle');
  const [wsStatus, setWsStatus] = useState<WSStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const wsClientRef = useRef<NirnayaWSClient | null>(null);
  // Set of message handlers registered by consumers
  const messageHandlers = useRef<Set<(frame: WSFrame) => void>>(new Set());

  // ------------------------------------------------------------------
  // Session + WS bootstrap (runs once on mount)
  // ------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      setSessionStatus('loading');
      setError(null);

      // ── 1. Session init ────────────────────────────────────────────
      let token: string;
      let sid: string;
      try {
        const state = await initSession();
        if (cancelled) return;
        token = state.token;
        sid = state.sessionId;
        setSessionId(sid);
        setSessionStatus('ready');
        console.debug('[useSession] Session ready:', sid);
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Session init failed';
          setError(msg);
          setSessionStatus('error');
          console.error('[useSession] Session init error:', err);
        }
        return;
      }

      // ── 2. WebSocket connect ───────────────────────────────────────
      setWsStatus('connecting');

      const client = new NirnayaWSClient(token, {
        onAuthSuccess: () => {
          if (!cancelled) {
            setWsStatus('connected');
            console.debug('[useSession] WS authenticated');
          }
        },
        onMessage: (frame) => {
          messageHandlers.current.forEach((handler) => handler(frame));
        },
        onClose: (code, reason) => {
          if (!cancelled) {
            if (code === 4001 || code === 4403) {
              setWsStatus('error');
              setError(`WebSocket auth rejected (code=${code}): ${reason}`);
            } else {
              setWsStatus('disconnected');
            }
          }
        },
        onError: () => {
          if (!cancelled) {
            setWsStatus('error');
          }
        },
      });

      wsClientRef.current = client;

      try {
        await client.connect();
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'WS connection failed';
          setError(msg);
          setWsStatus('error');
          console.error('[useSession] WS connect error:', err);
        }
      }
    }

    bootstrap();

    // ── Cleanup ────────────────────────────────────────────────────
    return () => {
      cancelled = true;
      if (wsClientRef.current) {
        wsClientRef.current.disconnect();
        wsClientRef.current = null;
      }
    };
  }, []); // runs once on mount

  // ------------------------------------------------------------------
  // submitKey — POST LLM provider key to the BE
  // ------------------------------------------------------------------

  const submitKey = useCallback(
    async (provider: 'openai' | 'anthropic', apiKey: string): Promise<void> => {
      try {
        await submitLLMKey(provider, apiKey);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to store API key';
        setError(msg);
        console.error('[useSession] submitKey error:', err);
        throw err;
      }
    },
    [],
  );

  // ------------------------------------------------------------------
  // onWSMessage — subscribe to inbound WS frames
  // ------------------------------------------------------------------

  const onWSMessage = useCallback((handler: (frame: WSFrame) => void): (() => void) => {
    messageHandlers.current.add(handler);
    return () => messageHandlers.current.delete(handler); // returns unsubscribe fn
  }, []);

  return {
    sessionId,
    wsClient: wsClientRef.current,
    sessionStatus,
    wsStatus,
    error,
    submitKey,
    onWSMessage,
  };
}
