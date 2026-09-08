"""
app/services/session_service.py
--------------------------------
Stateless session management backed by Upstash Redis.

Responsibilities
────────────────
1. Token lifecycle  — HMAC-SHA256 signed opaque tokens (no JWT lib).
2. Session records  — JSON blob in Redis with sliding TTL.
3. API key storage  — AES-256-GCM encrypted blob, decrypt only in-memory.
4. Chat history     — Capped Redis list (last 50 messages), same TTL as session.
5. Key validation   — Live round-trip to OpenAI / Anthropic before storing.

Redis key schema
────────────────
  session:{id}          STRING  session metadata JSON           TTL=SESSION_TTL
  session:{id}:key      STRING  encrypted API key JSON blob     TTL=SESSION_TTL
  session:{id}:history  LIST    JSON-encoded message objects    TTL=SESSION_TTL

All three keys share the same TTL; every write path refreshes it.

Security invariants
───────────────────
• Plaintext API key never written to disk, logs, or returned to caller.
• HMAC is verified with hmac.compare_digest (constant-time).
• AES-256-GCM auth tag validates ciphertext integrity on every decrypt.
• Key material is derived from KEY_ENCRYPTION_SECRET env var; cleared
  immediately after use (GC'd — Python has no explicit memory wipe).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from app.core.config import settings
from app.core.exceptions import LLMException, SessionException
from app.core.logging import get_logger
from app.services.redis_service import RedisService

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_SESSION_KEY = "session:{}"             # session metadata
_KEY_KEY = "session:{}:key"             # legacy single key key
_PROVIDER_KEY = "session:{}:key:{}"     # provider-specific key blob
_HISTORY_KEY = "session:{}:history"     # chat history list
_HISTORY_MAX = 50                       # max messages kept (LTRIM)


def _session_key(session_id: str) -> str:
    return _SESSION_KEY.format(session_id)


def _key_key(session_id: str, provider: str | None = None) -> str:
    if provider:
        return _PROVIDER_KEY.format(session_id, provider.lower())
    return _KEY_KEY.format(session_id)


def _history_key(session_id: str) -> str:
    return _HISTORY_KEY.format(session_id)



# ---------------------------------------------------------------------------
# AES-256-GCM helpers (cryptography library)
# ---------------------------------------------------------------------------

def _aes_key() -> bytes:
    """
    Derive the 32-byte AES key from KEY_ENCRYPTION_SECRET.
    Accepts a 64-char hex string (preferred) or falls back to
    SHA-256 of the raw string so the env var length is flexible.
    """
    raw = settings.key_encryption_secret
    if not raw:
        raise LLMException(
            "KEY_ENCRYPTION_SECRET is not set. "
            "Add it to your environment before storing API keys."
        )
    try:
        key_bytes = bytes.fromhex(raw)
        if len(key_bytes) >= 32:
            return key_bytes[:32]
    except ValueError:
        pass
    # Fallback: SHA-256 of the raw string bytes
    return hashlib.sha256(raw.encode()).digest()


def _encrypt(plaintext: str) -> dict[str, str]:
    """
    AES-256-GCM encrypt.  Returns {iv, ciphertext, tag} all base64-encoded.
    The auth tag (last 16 bytes of AESGCM.encrypt output) is split out so
    we can store it explicitly — easier to audit at rest.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # lazy import

    key = _aes_key()
    iv = os.urandom(12)  # 96-bit nonce, GCM standard
    aesgcm = AESGCM(key)
    # encrypt() appends the 16-byte auth tag to the ciphertext
    ct_and_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
    ciphertext = ct_and_tag[:-16]
    tag = ct_and_tag[-16:]
    return {
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "tag": base64.b64encode(tag).decode(),
    }


def _decrypt(blob: dict[str, str]) -> str:
    """
    AES-256-GCM decrypt.  Raises LLMException on integrity failure.
    The key bytes are cleared from the local scope as soon as decrypt returns.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    key = _aes_key()
    try:
        iv = base64.b64decode(blob["iv"])
        ciphertext = base64.b64decode(blob["ciphertext"])
        tag = base64.b64decode(blob["tag"])
        aesgcm = AESGCM(key)
        # Re-combine ciphertext + tag for AESGCM.decrypt
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
        return plaintext.decode()
    except (InvalidTag, KeyError, Exception) as exc:
        # Do NOT include exc details — could leak info about the key material
        raise LLMException("Failed to decrypt session API key.") from exc
    finally:
        del key  # best-effort; Python GC handles the rest


# ---------------------------------------------------------------------------
# HMAC-SHA256 token helpers
# ---------------------------------------------------------------------------
#
# Token format (URL-safe base64 of each segment, joined by '.'):
#   <session_id>.<expiry_unix_ts>.<HMAC-SHA256(secret, session_id:expiry)>
#
# This is intentionally simple — no JWT library dependency.

def _hmac_secret() -> bytes:
    raw = settings.session_secret
    if not raw:
        raise SessionException(
            "SESSION_SECRET is not set. "
            "Add it to your environment before creating sessions."
        )
    return raw.encode()


def _b64u_encode(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _b64u_decode(s: str) -> str:
    # Re-add padding
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (padding % 4)).decode()


def create_token(session_id: str, ttl: int | None = None) -> str:
    """Sign and return a new opaque bearer token for this session."""
    _ttl = ttl if ttl is not None else settings.session_ttl
    expiry = int(time.time()) + _ttl
    payload = f"{session_id}:{expiry}"
    sig = hmac.new(_hmac_secret(), payload.encode(), hashlib.sha256).hexdigest()
    parts = [_b64u_encode(session_id), _b64u_encode(str(expiry)), _b64u_encode(sig)]
    return ".".join(parts)


def verify_token(token: str) -> str | None:
    """
    Verify the token signature and expiry.
    Returns the session_id on success, None on any failure.
    Never raises — callers check for None.
    """
    try:
        sid_b64, exp_b64, sig_b64 = token.split(".", 2)
        session_id = _b64u_decode(sid_b64)
        expiry = int(_b64u_decode(exp_b64))
        provided_sig = _b64u_decode(sig_b64)

        if time.time() > expiry:
            return None  # expired

        payload = f"{session_id}:{expiry}"
        expected_sig = hmac.new(
            _hmac_secret(), payload.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(provided_sig, expected_sig):
            return None  # tampered

        return session_id
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SessionService — the public API
# ---------------------------------------------------------------------------

class SessionService:
    """
    All session operations.  Requires a RedisService instance — typically
    pulled from app.state in a FastAPI dependency.

    Do NOT store on app.state directly — create a thin factory dependency
    (see app/core/dependencies.py) that passes the redis service in.
    """

    def __init__(self, redis: RedisService) -> None:
        self._redis = redis

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def create_session(self) -> tuple[str, str]:
        """
        Create a new anonymous session.

        Returns:
            (session_id, token) — token is the HMAC-signed bearer string.
        """
        session_id = str(uuid.uuid4())
        now = int(time.time())
        data = {"created_at": now, "last_active": now}

        await self._redis.client.set(
            _session_key(session_id),
            json.dumps(data),
            ex=settings.session_ttl,
        )
        token = create_token(session_id)
        logger.info("session_created", session_id=session_id)
        return session_id, token

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the session metadata dict, or None if missing/expired."""
        raw = await self._redis.client.get(_session_key(session_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def refresh_session(self, session_id: str) -> None:
        """
        Slide the TTL for all session keys (metadata, keys, history).
        Called on activity and on ping.
        """
        ttl = settings.session_ttl
        pipe = self._redis.client.pipeline()
        pipe.expire(_session_key(session_id), ttl)
        pipe.expire(_key_key(session_id), ttl)
        pipe.expire(_key_key(session_id, "openai"), ttl)
        pipe.expire(_key_key(session_id, "anthropic"), ttl)
        pipe.expire(_history_key(session_id), ttl)
        await pipe.execute()

        # Update last_active in metadata (best-effort; don't fail on miss)
        raw = await self._redis.client.get(_session_key(session_id))
        if raw:
            try:
                data = json.loads(raw)
                data["last_active"] = int(time.time())
                await self._redis.client.set(
                    _session_key(session_id), json.dumps(data), ex=ttl
                )
            except Exception:
                pass  # non-critical

    async def delete_session(self, session_id: str) -> None:
        """Invalidate a session and all its sub-keys immediately."""
        pipe = self._redis.client.pipeline()
        pipe.delete(_session_key(session_id))
        pipe.delete(_key_key(session_id))
        pipe.delete(_key_key(session_id, "openai"))
        pipe.delete(_key_key(session_id, "anthropic"))
        pipe.delete(_history_key(session_id))
        await pipe.execute()
        logger.info("session_deleted", session_id=session_id)

    # ------------------------------------------------------------------
    # Token helpers (thin wrappers so callers don't import the module fns)
    # ------------------------------------------------------------------

    @staticmethod
    def sign_token(session_id: str) -> str:
        return create_token(session_id)

    @staticmethod
    def decode_token(token: str) -> str | None:
        return verify_token(token)

    # ------------------------------------------------------------------
    # API key storage (AES-256-GCM)
    # ------------------------------------------------------------------

    async def store_api_key(
        self, session_id: str, provider: str, api_key: str
    ) -> None:
        """
        Encrypt and persist the caller's API key.
        The plaintext key is never written to disk, logs, or returned.
        Stores under session:{id}:key:{provider} (and updates session:{id}:key).
        """
        prov = provider.lower()
        blob = _encrypt(api_key)
        blob["provider"] = prov
        payload = json.dumps(blob)

        pipe = self._redis.client.pipeline()
        pipe.set(_key_key(session_id, prov), payload, ex=settings.session_ttl)
        pipe.set(_key_key(session_id), payload, ex=settings.session_ttl)
        await pipe.execute()

        logger.info("api_key_stored", session_id=session_id, provider=prov)
        # Scrub plaintext immediately (Python GC, best-effort)
        del api_key

    async def get_api_key(
        self, session_id: str, provider: str | None = None
    ) -> tuple[str | None, str | None]:
        """
        Decrypt and return (provider, plaintext_key).
        Returns (None, None) if no key is stored for this session/provider.
        The plaintext key lives only in the caller's local scope.
        """
        raw = None
        if provider:
            raw = await self._redis.client.get(_key_key(session_id, provider.lower()))

        # Fallback to single legacy key if provider-specific key was not found
        if raw is None:
            raw = await self._redis.client.get(_key_key(session_id))

        if raw is None:
            return None, None

        try:
            blob: dict[str, str] = json.loads(raw)
            key_provider = blob.get("provider")
            # If a specific provider was requested, verify match
            if provider and key_provider and key_provider.lower() != provider.lower():
                return None, None
            plaintext = _decrypt(blob)
            return key_provider or provider, plaintext
        except Exception as exc:
            logger.warning("api_key_decrypt_failed", session_id=session_id, error=str(exc))
            return None, None

    async def has_api_key(self, session_id: str, provider: str | None = None) -> bool:
        """Return True if an encrypted key blob exists for this session."""
        if provider:
            result = await self._redis.client.exists(_key_key(session_id, provider.lower()))
            if result:
                return True
        return bool(await self._redis.client.exists(_key_key(session_id)))

    async def get_available_providers(self, session_id: str) -> list[str]:
        """Return list of providers configured for this session."""
        providers = []
        for prov in ["openai", "anthropic"]:
            if await self._redis.client.exists(_key_key(session_id, prov)):
                providers.append(prov)

        # If neither provider-specific key exists, check legacy key
        if not providers:
            legacy_prov, key = await self.get_api_key(session_id)
            if legacy_prov and key:
                providers.append(legacy_prov.lower())
                del key

        return providers

    # ------------------------------------------------------------------
    # API key validation (live provider round-trip before storing)
    # ------------------------------------------------------------------

    async def validate_openai_key(self, api_key: str) -> bool:
        """
        Confirm the key is valid by listing models (smallest API surface).
        Returns False on auth failure; returns False on unexpected errors too
        (network issues, rate limits) — we only store keys we can confirm.
        """
        import openai as _openai

        try:
            client = _openai.AsyncOpenAI(api_key=api_key)
            await client.models.list()
            return True
        except _openai.AuthenticationError:
            return False
        except _openai.OpenAIError as exc:
            logger.warning("openai_key_validation_error", error=str(exc))
            return False
        finally:
            del api_key  # best-effort scrub

    async def validate_anthropic_key(self, api_key: str) -> bool:
        """
        Confirm the Anthropic key by listing models.
        Returns False on auth failure.
        """
        try:
            import anthropic as _anthropic

            client = _anthropic.AsyncAnthropic(api_key=api_key)
            await client.models.list()
            return True
        except Exception as exc:
            err_str = str(exc).lower()
            if "authentication" in err_str or "401" in err_str or "invalid" in err_str:
                return False
            logger.warning("anthropic_key_validation_error", error=str(exc))
            return False
        finally:
            del api_key  # best-effort scrub

    # ------------------------------------------------------------------
    # Chat history  (capped Redis list, most-recent at tail)
    # ------------------------------------------------------------------

    async def append_history(
        self, session_id: str, role: str, content: str
    ) -> None:
        """Append one message to session:{id}:history; cap at _HISTORY_MAX entries."""
        msg = json.dumps({"role": role, "content": content, "ts": int(time.time())})
        key = _history_key(session_id)
        pipe = self._redis.client.pipeline()
        pipe.rpush(key, msg)
        pipe.ltrim(key, -_HISTORY_MAX, -1)  # keep last N
        pipe.expire(key, settings.session_ttl)
        await pipe.execute()

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return full chat history as a list of message dicts (oldest first)."""
        raw_list = await self._redis.client.lrange(_history_key(session_id), 0, -1)
        messages: list[dict[str, Any]] = []
        for raw in raw_list:
            try:
                messages.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return messages

    async def clear_history(self, session_id: str) -> None:
        """Delete the chat history list for this session."""
        await self._redis.client.delete(_history_key(session_id))
