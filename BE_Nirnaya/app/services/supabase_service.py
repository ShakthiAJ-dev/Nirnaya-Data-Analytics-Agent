"""
app/services/supabase_service.py
--------------------------------
Full Supabase integration — Auth, PostgreSQL (PostgREST), Storage, Realtime.

Two clients are initialised:
  • anon_client  — uses SUPABASE_ANON_KEY (safe for delegated user operations)
  • admin_client — uses SUPABASE_SERVICE_ROLE_KEY (server-side privileged ops,
                   bypasses RLS — never expose key to the frontend)

Usage:
    from app.services import supabase_service

    # Query the DB (admin)
    rows = await supabase_service.db("users").select("*").execute()

    # Auth — verify a JWT from the frontend
    user = await supabase_service.get_user(jwt)

    # Storage — upload a file
    await supabase_service.upload_file("nirnaya-uploads", "path/to/file.csv", data)
"""

from __future__ import annotations

import time
from typing import Any

from supabase import AsyncClient, acreate_client

from app.core.config import settings
from app.core.exceptions import DatabaseException
from app.core.logging import get_logger

logger = get_logger(__name__)


class SupabaseService:
    """
    Wraps the Supabase async client.
    Initialise once in lifespan; attach to app.state.
    """

    def __init__(self) -> None:
        self._anon: AsyncClient | None = None
        self._admin: AsyncClient | None = None

    async def initialize(self) -> None:
        """Async initialiser — called inside lifespan startup."""
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise DatabaseException(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set."
            )

        try:
            self._anon = await acreate_client(
                settings.supabase_url,
                settings.supabase_anon_key,
            )
            logger.info("supabase_anon_client_ready", url=settings.supabase_url)
        except Exception as e:
            raise DatabaseException(f"Failed to create Supabase anon client: {e}") from e

        if settings.supabase_service_role_key:
            try:
                self._admin = await acreate_client(
                    settings.supabase_url,
                    settings.supabase_service_role_key,
                )
                logger.info("supabase_admin_client_ready")
            except Exception as e:
                logger.warning("supabase_admin_client_failed", error=str(e))
        else:
            logger.warning(
                "supabase_admin_client_skipped",
                reason="SUPABASE_SERVICE_ROLE_KEY not set",
            )

    async def close(self) -> None:
        """Graceful shutdown — called inside lifespan teardown."""
        # supabase-py v2 manages its own httpx sessions internally;
        # explicit close is a no-op but keeps the interface clean.
        logger.info("supabase_service_closed")

    # ------------------------------------------------------------------
    # Client accessors
    # ------------------------------------------------------------------

    @property
    def anon(self) -> AsyncClient:
        """Public / anon-key client (respects RLS)."""
        if not self._anon:
            raise DatabaseException("SupabaseService is not initialised.")
        return self._anon

    @property
    def admin(self) -> AsyncClient:
        """Service-role client (bypasses RLS) — server-side only."""
        if not self._admin:
            raise DatabaseException(
                "Supabase admin client is not available (no SERVICE_ROLE_KEY)."
            )
        return self._admin

    # ------------------------------------------------------------------
    # Convenience — Database
    # ------------------------------------------------------------------

    def db(self, table: str, *, use_admin: bool = False):
        """
        Return a PostgREST query builder for `table`.

        Example:
            rows = await svc.db("users").select("id, email").execute()
        """
        client = self.admin if use_admin else self.anon
        return client.table(table)

    # ------------------------------------------------------------------
    # Convenience — Auth
    # ------------------------------------------------------------------

    async def get_user(self, jwt: str) -> dict[str, Any]:
        """
        Verify and decode a Supabase JWT; return the user dict.
        Raises DatabaseException on failure.
        """
        try:
            resp = await self.anon.auth.get_user(jwt)
            if not resp.user:
                raise DatabaseException("Invalid or expired JWT.")
            return resp.user.model_dump()
        except DatabaseException:
            raise
        except Exception as e:
            raise DatabaseException(f"Auth.get_user failed: {e}") from e

    async def sign_up(self, email: str, password: str) -> dict[str, Any]:
        """Register a new user with email + password."""
        try:
            resp = await self.anon.auth.sign_up({"email": email, "password": password})
            return {"user": resp.user.model_dump() if resp.user else None}
        except Exception as e:
            raise DatabaseException(f"Auth.sign_up failed: {e}") from e

    async def sign_in(self, email: str, password: str) -> dict[str, Any]:
        """Sign in with email + password; return session tokens."""
        try:
            resp = await self.anon.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            session = resp.session
            return {
                "access_token": session.access_token if session else None,
                "refresh_token": session.refresh_token if session else None,
                "user": resp.user.model_dump() if resp.user else None,
            }
        except Exception as e:
            raise DatabaseException(f"Auth.sign_in failed: {e}") from e

    # ------------------------------------------------------------------
    # Convenience — Storage
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        bucket: str,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        upsert: bool = False,
    ) -> dict[str, Any]:
        """Upload a file to a Supabase Storage bucket."""
        try:
            resp = await self.admin.storage.from_(bucket).upload(
                path=path,
                file=data,
                file_options={"content-type": content_type, "upsert": str(upsert).lower()},
            )
            return {"path": resp.path if hasattr(resp, "path") else path}
        except Exception as e:
            raise DatabaseException(f"Storage.upload failed: {e}") from e

    def get_public_url(self, bucket: str, path: str) -> str:
        """Return the public URL for a storage object (public bucket only)."""
        return self.anon.storage.from_(bucket).get_public_url(path)

    async def delete_file(self, bucket: str, paths: list[str]) -> None:
        """Remove one or more objects from a storage bucket."""
        try:
            await self.admin.storage.from_(bucket).remove(paths)
        except Exception as e:
            raise DatabaseException(f"Storage.delete failed: {e}") from e

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> tuple[bool, float]:
        """
        Ping the Supabase PostgREST endpoint with a lightweight request.
        Returns (is_healthy, latency_ms).

        Strategy: call a dummy RPC. If Supabase responds with any HTTP reply
        (even 404 / PGRST202 "function not found") the connection is alive.
        Only a network / timeout error means the service is truly down.
        """
        t0 = time.monotonic()
        try:
            await self.admin.rpc("health_check", {}).execute()
            return True, (time.monotonic() - t0) * 1000
        except Exception as e:
            err_str = str(e).lower()
            # PGRST202 = "Could not find the function" — PostgREST is reachable,
            # the RPC just doesn't exist. Connection is healthy.
            if "pgrst202" in err_str or "could not find the function" in err_str:
                return True, (time.monotonic() - t0) * 1000
            return False, (time.monotonic() - t0) * 1000
