"""
tests/test_supabase.py
----------------------
Quick smoke-test for SupabaseService.

Run with:
    cd BE_Nirnaya
    python -m tests.test_supabase
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.supabase_service import SupabaseService


async def main() -> None:
    svc = SupabaseService()

    # ── 1. Initialize (reads SUPABASE_URL + SUPABASE_ANON_KEY from .env) ─
    print("Initializing SupabaseService...")
    await svc.initialize()
    print("✓ Supabase clients ready\n")

    # ── 2. Health check ──────────────────────────────────────────────────
    healthy, latency_ms = await svc.health_check()
    print(f"Health check → healthy={healthy}, latency={latency_ms:.1f} ms\n")

    # ── 3. DB query — read rows from a table (admin client, bypasses RLS) ─
    # Change "users" to any table that exists in your Supabase project.
    print("Querying 'users' table (admin, select id+email, limit 3)...")
    try:
        result = await svc.db("users", use_admin=True).select("id, email").limit(3).execute()
        print(f"Rows returned: {result.data}\n")
    except Exception as e:
        print(f"DB query failed (table may not exist): {e}\n")

    # ── 4. Auth — sign up a test user (comment out after first run) ───────
    # print("Signing up test user...")
    # resp = await svc.sign_up("test_nirnaya@example.com", "password123!")
    # print(f"sign_up → {resp}\n")

    # ── 5. Auth — sign in ────────────────────────────────────────────────
    # print("Signing in test user...")
    # tokens = await svc.sign_in("test_nirnaya@example.com", "password123!")
    # print(f"access_token (first 30 chars): {tokens['access_token'][:30]}...\n")

    # ── 6. Storage — get public URL (no upload needed) ───────────────────
    # Change "nirnaya-uploads" and "sample.csv" to real values.
    try:
        url = svc.get_public_url("nirnaya-uploads", "sample.csv")
        print(f"Public URL → {url}\n")
    except Exception as e:
        print(f"get_public_url (bucket may not exist): {e}\n")

    # ── 7. Close ─────────────────────────────────────────────────────────
    await svc.close()
    print("✓ SupabaseService closed. All tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
