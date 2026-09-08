"""
tests/test_data_service.py
--------------------------
Smoke-test for DataService (TableService + FileService).

Tests
-----
  1. TableService -- ensure_table("chat_history")  (idempotent DDL)
  2. TableService -- insert a chat message
  3. TableService -- select chat history for the session
  4. TableService -- append_chat_message shortcut (assistant reply)
  5. TableService -- get_chat_history shortcut
  6. TableService -- delete a specific row
  7. FileService  -- ensure_bucket() 'nirnaya-sessions'
  8. FileService  -- upload a text file
  9. FileService  -- download the uploaded file & verify contents
 10. FileService  -- upload a PNG image (binary)
 11. FileService  -- list files in the session directory
 12. FileService  -- create a signed URL for the text file
 13. FileService  -- delete all uploaded test files
 14. Cleanup      -- delete all chat rows for this session

Run with (Windows):
    cd BE_Nirnaya
    set PYTHONUTF8=1 && .venv\Scripts\python.exe -m tests.test_data_service
"""

import asyncio
import os
import sys

# ── Path setup so imports resolve from BE_Nirnaya/ ──────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env BEFORE importing app modules (pydantic-settings reads env at import)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.services.supabase_service import SupabaseService
from app.services.data_service import DataService


# ============================================================================
# STAR SET YOUR SESSION ID HERE -- used as the partition key for all operations
# ============================================================================
SESSION_ID = "6f07b046-8e99-4635-8983-c6fb7762a2cc"
# ============================================================================


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")

def _section(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")

def _fail(msg: str, exc: Exception) -> None:
    print(f"  [FAIL]  {msg}")
    print(f"          Error: {exc}")


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  DataService Smoke Test")
    print(f"  session_id = {SESSION_ID!r}")
    print("=" * 60)

    # ── Bootstrap Supabase ──────────────────────────────────────────────────
    _section("Bootstrapping SupabaseService")
    supabase = SupabaseService()
    await supabase.initialize()
    _ok("SupabaseService ready")

    healthy, latency = await supabase.health_check()
    _ok(f"Supabase health: healthy={healthy}, latency={latency:.1f} ms")

    # ── Create DataService scoped to our session ────────────────────────────
    ds = DataService(session_id=SESSION_ID, supabase=supabase)
    _ok(f"DataService created (session_id={ds.session_id!r})")

    # =========================================================================
    # TABLE SERVICE TESTS
    # =========================================================================
    _section("TableService — 1. ensure_table('chat_history')")
    try:
        await ds.table.ensure_table("chat_history")
        _ok("ensure_table('chat_history') completed (idempotent DDL)")
    except Exception as e:
        _fail("ensure_table failed", e)
        print("\n  ⚠  If you see 'exec_ddl RPC missing', run supabase_setup.sql first.")
        print("     The table might already exist — continuing anyway...\n")

    # ── 2. Insert a chat row ─────────────────────────────────────────────────
    _section("TableService — 2. insert() a user message")
    inserted_id: int | None = None
    try:
        row = await ds.table.insert(
            "chat_history",
            {
                "role": "user",
                "content": "Hello, Nirnaya! This is a test message.",
                "metadata": {"source": "test_data_service", "token_count": 12},
            },
        )
        inserted_id = row.get("id")
        _ok(f"Inserted row → id={inserted_id}, role={row.get('role')!r}")
        _ok(f"created_at  → {row.get('created_at')}")
    except Exception as e:
        _fail("insert() failed", e)

    # ── 3. Select — raw select with filter ──────────────────────────────────
    _section("TableService — 3. select() with role filter")
    try:
        rows = await ds.table.select(
            "chat_history",
            filters={"role": "user"},
        )
        _ok(f"select(role='user') returned {len(rows)} row(s)")
        for r in rows:
            print(f"     id={r.get('id'):<6} role={r.get('role'):<12} content={r.get('content')[:40]!r}")
    except Exception as e:
        _fail("select() failed", e)

    # ── 4. append_chat_message shortcut ─────────────────────────────────────
    _section("TableService — 4. append_chat_message() shortcut")
    try:
        reply = await ds.table.append_chat_message(
            role="assistant",
            content="Hello! I'm Nirnaya. How can I help you with your data today?",
            metadata={"model": "claude-haiku-4-5", "latency_ms": 342},
        )
        _ok(f"assistant message inserted → id={reply.get('id')}")
    except Exception as e:
        _fail("append_chat_message() failed", e)

    # ── 5. get_chat_history shortcut ─────────────────────────────────────────
    _section("TableService — 5. get_chat_history() shortcut")
    try:
        history = await ds.table.get_chat_history()
        _ok(f"get_chat_history() → {len(history)} message(s) (oldest first)")
        for msg in history:
            print(f"     [{msg.get('role'):<10}] {msg.get('content')[:55]!r}")
    except Exception as e:
        _fail("get_chat_history() failed", e)

    # ── 6. Delete a specific row ─────────────────────────────────────────────
    _section("TableService — 6. delete() by row_id")
    if inserted_id is not None:
        try:
            deleted = await ds.table.delete("chat_history", row_id=inserted_id)
            _ok(f"delete(row_id={inserted_id}) → {deleted} row(s) removed")
        except Exception as e:
            _fail("delete() failed", e)
    else:
        print("  ⚠  Skipped (no inserted_id from step 2)")

    # =========================================================================
    # FILE SERVICE TESTS
    # =========================================================================
    _section("FileService — 7. ensure_bucket() 'nirnaya-sessions'")
    try:
        await ds.file.ensure_bucket(public=False)
        _ok("ensure_bucket('nirnaya-sessions') — bucket ready")
    except Exception as e:
        _fail("ensure_bucket() failed", e)
        print("  ⚠  Cannot proceed with file tests — check your SUPABASE_SERVICE_ROLE_KEY")

    _section("FileService — 8. upload() a text file")
    text_sub_path = "uploads/hello_nirnaya.txt"
    text_content = (
        f"Session: {SESSION_ID}\n"
        "This is a test file uploaded by test_data_service.py\n"
        "Line 3: all systems nominal.\n"
    ).encode("utf-8")

    uploaded_text_path: str | None = None
    try:
        uploaded_text_path = await ds.file.upload(
            text_sub_path,
            text_content,
            content_type="text/plain",
        )
        _ok(f"upload() → stored at: {uploaded_text_path!r}")
    except Exception as e:
        _fail("upload() text file failed", e)

    # ── 9. Download and verify ───────────────────────────────────────────────
    _section("FileService — 9. download() and verify contents")
    try:
        downloaded = await ds.file.download(text_sub_path)
        assert downloaded == text_content, "Content mismatch!"
        _ok(f"download() → {len(downloaded)} bytes received")
        _ok(f"Content verified: {downloaded.decode()[:60]!r} ...")
    except AssertionError:
        print("  ✗  Content mismatch between uploaded and downloaded bytes!")
    except Exception as e:
        _fail("download() failed", e)

    # ── 10. Upload a binary (PNG-like) image ─────────────────────────────────
    _section("FileService — 10. upload() a PNG image (binary)")
    image_sub_path = "images/test_chart.png"
    # Minimal valid PNG header (89 bytes of real PNG magic + IHDR)
    fake_png = (
        b"\x89PNG\r\n\x1a\n"           # PNG magic
        b"\x00\x00\x00\rIHDR"          # IHDR chunk length + type
        b"\x00\x00\x00\x01"            # width: 1
        b"\x00\x00\x00\x01"            # height: 1
        b"\x08\x02"                    # bit depth 8, colour type RGB
        b"\x00\x00\x00"               # compression, filter, interlace
        b"\x90wS\xde"                  # CRC
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"  # IDAT
        b"\x00\x00\x00\x00IEND\xaeB`\x82"  # IEND
    )
    try:
        img_path = await ds.file.upload(
            image_sub_path,
            fake_png,
            content_type="image/png",
        )
        _ok(f"upload() image → {img_path!r} ({len(fake_png)} bytes)")
    except Exception as e:
        _fail("upload() image failed", e)

    # ── 11. List files ───────────────────────────────────────────────────────
    _section("FileService — 11. list_files() for this session")
    try:
        files = await ds.file.list_files()
        _ok(f"list_files() → {len(files)} object(s) under '{SESSION_ID}/'")
        for f in files:
            name = f.get("name", "<unknown>")
            size = f.get("metadata", {}).get("size", "?")
            print(f"     {name:<40}  ({size} bytes)")
    except Exception as e:
        _fail("list_files() failed", e)

    # ── 12. Signed URL ───────────────────────────────────────────────────────
    _section("FileService — 12. create_signed_url() (1 hour)")
    try:
        signed_url = await ds.file.create_signed_url(text_sub_path, expires_in=3600)
        _ok("create_signed_url() → URL generated")
        print(f"     {signed_url[:80]}{'...' if len(signed_url) > 80 else ''}")
    except Exception as e:
        _fail("create_signed_url() failed", e)

    # ── 13. Delete uploaded files ────────────────────────────────────────────
    _section("FileService — 13. delete() uploaded files")
    # try:
    #     await ds.file.delete(text_sub_path, image_sub_path)
    #     _ok(f"delete({text_sub_path!r}, {image_sub_path!r}) → done")
    # except Exception as e:
    #     _fail("delete() files failed", e)

    # ── 14. Cleanup — delete remaining chat rows ─────────────────────────────
    _section("Cleanup — 14. delete ALL chat rows for this session")
    try:
        deleted = await ds.table.delete("chat_history")
        _ok(f"Deleted {deleted} remaining chat_history row(s) for session")
    except Exception as e:
        _fail("cleanup delete() failed", e)

    # ── Final summary ────────────────────────────────────────────────────────
    await supabase.close()
    print("\n" + "=" * 60)
    print("  [DONE] DataService smoke test complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
