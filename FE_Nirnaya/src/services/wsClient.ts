/**
 * src/services/wsClient.ts
 * -------------------------
 * NirnayaWSClient — WebSocket client for /ws/agent.
 *
 * Protocol (matches BE ws_agent.py):
 * ────────────────────────────────────
 * 1. Connect to ws://localhost:8000/ws/agent
 * 2. On open → send { type: "auth", token: "<HMAC token>" }
 * 3. BE validates token + Redis session → sends no ack (silent success)
 *    or closes(4001) on failure
 * 4. Ping/Pong keepalive every 30s to slide session TTL
 * 5. When chat message is ready → call sendChatMessage(prompt, txId)
 *    → BE receives, processes, streams back { type: "stream", content: "..." }
 *    → Final frame: { type: "complete", ... }
 *
 * Usage:
 *   const ws = new NirnayaWSClient(token, {
 *     onMessage: (frame) => ...,
 *     onAuthSuccess: () => ...,
 *     onClose: (code, reason) => ...,
 *   });
 *   await ws.connect();
 *   ws.sendChatMessage('Analyze Q3 revenue', 'tx-001');
 *   ws.disconnect();
 */

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';

// ---------------------------------------------------------------------------
// Frame types (mirrors BE _make_frame output)
// ---------------------------------------------------------------------------

export type WSFrameType =
  | 'auth'
  | 'ping'
  | 'pong'
  | 'chat_message'
  | 'stream'
  | 'complete'
  | 'error'
  | 'cancel';

export interface WSFrame {
  type: WSFrameType;
  transactionId: string;
  content: string;
  timestamp: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Client callbacks
// ---------------------------------------------------------------------------

export interface WSClientCallbacks {
  /** Called when auth succeeds (BE accepted the token, session is live) */
  onAuthSuccess?: () => void;
  /** Called for every inbound frame after auth */
  onMessage?: (frame: WSFrame) => void;
  /** Called when the connection closes — code 4001 = auth failure */
  onClose?: (code: number, reason: string) => void;
  /** Called on any WebSocket error event */
  onError?: (event: Event) => void;
}

// ---------------------------------------------------------------------------
// NirnayaWSClient
// ---------------------------------------------------------------------------

export class NirnayaWSClient {
  private ws: WebSocket | null = null;
  private token: string;
  private callbacks: WSClientCallbacks;
  private pingInterval: ReturnType<typeof setInterval> | null = null;
  private authAcknowledged = false;
  private pendingPingIds: Set<string> = new Set();

  /** Number of automatic reconnect attempts remaining */
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 3;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

  constructor(token: string, callbacks: WSClientCallbacks = {}) {
    this.token = token;
    this.callbacks = callbacks;
  }

  // ------------------------------------------------------------------
  // Connect / Disconnect
  // ------------------------------------------------------------------

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        resolve();
        return;
      }

      console.debug('[ws] Connecting to', `${WS_BASE_URL}/ws/agent`);
      this.ws = new WebSocket(`${WS_BASE_URL}/ws/agent`);

      // ── onopen: send auth frame immediately ────────────────────────
      this.ws.onopen = () => {
        console.debug('[ws] Connection open — sending auth frame');
        this._send({ type: 'auth', token: this.token });

        // 10s timeout: BE closes(4001) if auth fails, resolve here
        // assumes BE doesn't send an explicit ack on success (silent)
        const authTimeout = setTimeout(() => {
          if (!this.authAcknowledged) {
            console.debug('[ws] Auth assumed successful (no close received)');
            this.authAcknowledged = true;
            this._startPing();
            this.callbacks.onAuthSuccess?.();
            resolve();
          }
        }, 1500);

        // If we get a close(4001) during the window, reject
        const prevOnClose = this.ws!.onclose;
        this.ws!.onclose = (ev) => {
          clearTimeout(authTimeout);
          if (!this.authAcknowledged) {
            reject(new Error(`WS auth failed (code=${ev.code}): ${ev.reason}`));
          }
          if (prevOnClose) {
            (prevOnClose as (ev: CloseEvent) => void)(ev);
          }
        };
      };

      // ── onmessage: route frames ────────────────────────────────────
      this.ws.onmessage = (ev) => {
        let frame: WSFrame;
        try {
          frame = JSON.parse(ev.data as string) as WSFrame;
        } catch {
          console.warn('[ws] Malformed frame received:', ev.data);
          return;
        }

        // Pong — remove from pending set
        if (frame.type === 'pong') {
          this.pendingPingIds.delete(frame.transactionId);
          console.debug('[ws] Pong received for tx:', frame.transactionId);
          return;
        }

        this.callbacks.onMessage?.(frame);
      };

      // ── onclose ───────────────────────────────────────────────────
      this.ws.onclose = (ev) => {
        console.debug(`[ws] Closed (code=${ev.code}): ${ev.reason}`);
        this._stopPing();
        this.callbacks.onClose?.(ev.code, ev.reason);

        // Auto-reconnect on abnormal close (not auth failures, not manual)
        if (
          ev.code !== 1000 &&   // normal close
          ev.code !== 4001 &&   // auth failure — don't retry
          ev.code !== 4403 &&   // origin blocked — don't retry
          this.reconnectAttempts < this.maxReconnectAttempts
        ) {
          this._scheduleReconnect();
        }
      };

      // ── onerror ───────────────────────────────────────────────────
      this.ws.onerror = (ev) => {
        console.error('[ws] Error event:', ev);
        this.callbacks.onError?.(ev);
        // onerror is always followed by onclose — let onclose handle reconnect
      };
    });
  }

  /** Gracefully close the connection. */
  disconnect(): void {
    this._clearReconnect();
    this._stopPing();
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.authAcknowledged = false;
  }

  // ------------------------------------------------------------------
  // Send helpers
  // ------------------------------------------------------------------

  /** Send a chat message to the agent. Returns the transaction ID. */
  sendChatMessage(prompt: string, transactionId?: string): string {
    const txId = transactionId ?? this._genTxId();
    this._sendFrame('chat_message', txId, prompt);
    return txId;
  }

  /** Cancel an in-flight transaction. */
  cancelTransaction(transactionId: string): void {
    this._sendFrame('cancel', transactionId, '');
  }

  /** Check if the socket is open and authenticated. */
  get isReady(): boolean {
    return (
      this.ws !== null &&
      this.ws.readyState === WebSocket.OPEN &&
      this.authAcknowledged
    );
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------

  private _send(payload: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    } else {
      console.warn('[ws] Attempted to send on non-open socket');
    }
  }

  private _sendFrame(
    requestType: WSFrameType,
    transactionId: string,
    content: string,
    extra?: Record<string, unknown>,
  ): void {
    this._send({
      requestType,
      transactionId,
      content,
      timestamp: Math.floor(Date.now() / 1000),
      ...extra,
    });
  }

  private _startPing(): void {
    this.pingInterval = setInterval(() => {
      if (!this.isReady) return;
      const txId = this._genTxId('ping');
      this.pendingPingIds.add(txId);
      this._sendFrame('ping', txId, '');
      console.debug('[ws] Ping sent tx:', txId);
    }, 30_000); // every 30s — keeps Redis TTL sliding
  }

  private _stopPing(): void {
    if (this.pingInterval !== null) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private _scheduleReconnect(): void {
    this.reconnectAttempts += 1;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 15_000);
    console.debug(`[ws] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimeout = setTimeout(() => {
      this.connect().catch((e) => console.error('[ws] Reconnect failed:', e));
    }, delay);
  }

  private _clearReconnect(): void {
    if (this.reconnectTimeout !== null) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
  }

  private _genTxId(prefix = 'tx'): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  }
}
