"""
app/services/data_service/file_service.py
------------------------------------------
FileService — Supabase Storage operations, session-partitioned.

Responsibilities
────────────────
1. Upload files    — content, images, any binary from the caller.
2. Download files  — retrieve bytes from storage by path.
3. Delete files    — remove objects from a bucket.
4. List files      — enumerate all objects under a session's prefix.
5. Signed URLs     — generate time-limited download URLs for private buckets.

Storage Layout (volume structure)
──────────────────────────────────
All files for a session live under a path prefix keyed by session_id:

    Bucket: nirnaya-sessions
    Path:   {session_id}/{sub_path}

Examples:
    abc-123/uploads/report.csv
    abc-123/images/chart.png
    abc-123/exports/analysis_2024.json

This gives each session its own "folder" inside the shared bucket,
providing logical isolation without requiring a bucket-per-session.

The session_id acts as the partition key — just like in TableService.

Usage
─────
    ds = DataService(session_id="abc-123", supabase=supabase_service)

    # Upload
    url = await ds.file.upload("my_data.csv", csv_bytes, content_type="text/csv")

    # Download
    data = await ds.file.download("my_data.csv")

    # List all files for this session
    files = await ds.file.list_files()

    # Delete
    await ds.file.delete("my_data.csv")
"""

from __future__ import annotations

import mimetypes
import posixpath
from typing import Any

from app.core.exceptions import DatabaseException
from app.core.logging import get_logger
from app.services.supabase_service import SupabaseService

logger = get_logger(__name__)

# Default bucket name — can be overridden at construction time
_DEFAULT_BUCKET = "nirnaya-sessions"

# In-process cache of buckets we've already confirmed exist.
# Resets on server restart (acceptable — bucket creation is idempotent).
_ENSURED_BUCKETS: set[str] = set()


class FileService:
    """
    Session-scoped Supabase Storage file operations.

    All paths are automatically namespaced under ``{session_id}/``
    so each session has its own isolated directory in the bucket.

    Parameters
    ──────────
    session_id : str             — the owning session (used as path prefix)
    supabase   : SupabaseService — shared singleton from app.state
    bucket     : str             — Supabase Storage bucket name
    """

    def __init__(
        self,
        session_id: str,
        supabase: SupabaseService,
        *,
        bucket: str = _DEFAULT_BUCKET,
    ) -> None:
        self._session_id = session_id
        self._supa = supabase
        self._bucket = bucket

    # ------------------------------------------------------------------
    # Bucket management
    # ------------------------------------------------------------------

    async def ensure_bucket(
        self,
        *,
        public: bool = False,
        file_size_limit: int = 52_428_800,  # 50 MB default
        allowed_mime_types: list[str] | None = None,
    ) -> None:
        """
        Ensure the bucket exists in Supabase Storage. Creates it if absent.

        Parameters
        ──────────
        public             : make the bucket publicly accessible (default False)
        file_size_limit    : max file size in bytes (default 50 MB)
        allowed_mime_types : restrict allowed MIME types (None = all allowed)

        This is idempotent — calling it multiple times is safe.
        The result is cached in-process so the check only runs once per
        server boot.
        """
        if self._bucket in _ENSURED_BUCKETS:
            return

        try:
            options: dict[str, Any] = {
                "public": public,
                "file_size_limit": file_size_limit,
            }
            if allowed_mime_types:
                options["allowed_mime_types"] = allowed_mime_types

            await self._supa.admin.storage.create_bucket(
                self._bucket,
                options=options,
            )
            _ENSURED_BUCKETS.add(self._bucket)
            logger.info("bucket_created", bucket=self._bucket, public=public)

        except Exception as exc:
            err = str(exc).lower()
            # "already exists" / duplicate → bucket is there, just mark it
            if "already exists" in err or "duplicate" in err or "409" in err:
                _ENSURED_BUCKETS.add(self._bucket)
                logger.info("bucket_already_exists", bucket=self._bucket)
            else:
                raise DatabaseException(
                    f"FileService.ensure_bucket failed for '{self._bucket}': {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _full_path(self, sub_path: str) -> str:
        """
        Prepend the session_id prefix to form the full storage path.

        Example:
            session_id = "abc-123"
            sub_path   = "uploads/report.csv"
            result     = "abc-123/uploads/report.csv"
        """
        # Normalise: strip leading slash, rejoin cleanly
        clean = sub_path.lstrip("/")
        return posixpath.join(self._session_id, clean)

    def _guess_content_type(self, filename: str) -> str:
        """Guess MIME type from filename extension."""
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload(
        self,
        sub_path: str,
        data: bytes,
        *,
        content_type: str | None = None,
        upsert: bool = True,
        auto_ensure: bool = True,
    ) -> str:
        """
        Upload `data` to storage at ``{session_id}/{sub_path}``.

        Parameters
        ──────────
        sub_path     : file path relative to this session's root
                       (e.g. "uploads/report.csv" or "images/chart.png")
        data         : raw bytes to upload
        content_type : MIME type (auto-detected from extension if None)
        upsert       : overwrite if file already exists (default True)

        Returns
        ───────
        The full storage path (str) of the uploaded object.
        """
        if auto_ensure:
            await self.ensure_bucket()

        path = self._full_path(sub_path)
        mime = content_type or self._guess_content_type(sub_path)

        try:
            resp = await self._supa.admin.storage.from_(self._bucket).upload(
                path=path,
                file=data,
                file_options={
                    "content-type": mime,
                    "upsert": "true" if upsert else "false",
                },
            )
            stored_path = resp.path if hasattr(resp, "path") else path
            logger.info(
                "file_uploaded",
                session_id=self._session_id,
                path=stored_path,
                bytes=len(data),
            )
            return stored_path
        except Exception as exc:
            raise DatabaseException(
                f"FileService.upload failed for '{path}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download(self, sub_path: str, *, auto_ensure: bool = True) -> bytes:
        """
        Download and return the raw bytes of ``{session_id}/{sub_path}``.

        Raises DatabaseException if the file does not exist or access fails.
        """
        if auto_ensure:
            await self.ensure_bucket()

        path = self._full_path(sub_path)

        try:
            data: bytes = await self._supa.admin.storage.from_(self._bucket).download(path)
            logger.info(
                "file_downloaded",
                session_id=self._session_id,
                path=path,
                bytes=len(data),
            )
            return data
        except Exception as exc:
            raise DatabaseException(
                f"FileService.download failed for '{path}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, *sub_paths: str, auto_ensure: bool = True) -> None:
        """
        Delete one or more files from this session's storage directory.

        Parameters
        ──────────
        *sub_paths : one or more paths relative to this session's root.

        Example:
            await file_svc.delete("uploads/old.csv", "images/tmp.png")
        """
        if not sub_paths:
            return

        if auto_ensure:
            await self.ensure_bucket()

        full_paths = [self._full_path(p) for p in sub_paths]

        try:
            await self._supa.admin.storage.from_(self._bucket).remove(full_paths)
            logger.info(
                "files_deleted",
                session_id=self._session_id,
                paths=full_paths,
            )
        except Exception as exc:
            raise DatabaseException(
                f"FileService.delete failed for {full_paths}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_files(
        self,
        *,
        sub_folder: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List all files under this session's storage directory.

        Parameters
        ──────────
        sub_folder : optional sub-directory to list within the session root
                     (e.g. "uploads" to list only abc-123/uploads/)
        limit      : max objects to return (default 100)
        offset     : pagination offset

        Returns
        ───────
        List of Supabase storage object metadata dicts, each containing:
            { name, id, updated_at, created_at, last_accessed_at, metadata }
        """
        if auto_ensure:
            await self.ensure_bucket()

        prefix = self._full_path(sub_folder) if sub_folder else self._session_id

        try:
            resp = await self._supa.admin.storage.from_(self._bucket).list(
                path=prefix,
                options={"limit": limit, "offset": offset},
            )
            return resp or []
        except Exception as exc:
            raise DatabaseException(
                f"FileService.list_files failed under '{prefix}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Signed URL (for private bucket downloads via the client)
    # ------------------------------------------------------------------

    async def create_signed_url(
        self,
        sub_path: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """
        Generate a signed (time-limited) URL for a private file.

        Parameters
        ──────────
        sub_path   : file path relative to this session's root
        expires_in : URL validity in seconds (default 1 hour)

        Returns
        ───────
        A signed URL string. Share this with the client; it expires after
        `expires_in` seconds.
        """
        path = self._full_path(sub_path)

        try:
            resp = await self._supa.admin.storage.from_(self._bucket).create_signed_url(
                path=path,
                expires_in=expires_in,
            )
            signed_url: str = resp.get("signedURL") or resp.get("signed_url", "")
            logger.info(
                "signed_url_created",
                session_id=self._session_id,
                path=path,
                expires_in=expires_in,
            )
            return signed_url
        except Exception as exc:
            raise DatabaseException(
                f"FileService.create_signed_url failed for '{path}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Public URL (for public buckets)
    # ------------------------------------------------------------------

    def get_public_url(self, sub_path: str) -> str:
        """
        Return the public URL for a file in a **public** bucket.
        This is a synchronous method (no network call needed).
        """
        path = self._full_path(sub_path)
        return self._supa.get_public_url(self._bucket, path)

    # ------------------------------------------------------------------
    # Move / Copy
    # ------------------------------------------------------------------

    async def move(self, from_sub_path: str, to_sub_path: str) -> None:
        """
        Move/rename a file within this session's storage directory.
        Both paths are automatically prefixed with session_id.
        """
        from_path = self._full_path(from_sub_path)
        to_path = self._full_path(to_sub_path)

        try:
            await self._supa.admin.storage.from_(self._bucket).move(
                from_path=from_path,
                to_path=to_path,
            )
            logger.info(
                "file_moved",
                session_id=self._session_id,
                from_path=from_path,
                to_path=to_path,
            )
        except Exception as exc:
            raise DatabaseException(
                f"FileService.move failed '{from_path}' → '{to_path}': {exc}"
            ) from exc
