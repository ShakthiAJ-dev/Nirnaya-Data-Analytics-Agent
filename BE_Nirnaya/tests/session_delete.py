"""
Standalone test: call DatabaseService.cleanup_session() directly.

Run from BE_Nirnaya/ dir:
    python -m tests.session_delete

Or with a different session_id:
    SESSION_ID=<id> python -m tests.session_delete
"""

import asyncio
import os
import sys

# Make sure app/ is importable when run from BE_Nirnaya/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load .env before any app imports so pydantic-settings picks up the values
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

SESSION_ID = os.environ.get("SESSION_ID", "15c694d1-ae20-4580-beee-a14887df7eae")


async def main() -> None:
    from app.services.supabase_service import SupabaseService
    from app.services.database_service import DatabaseService

    print(f"[cleanup] session_id = {SESSION_ID}")

    supa = SupabaseService()
    await supa.initialize()

    svc = DatabaseService(SESSION_ID, supa)
    result = await svc.cleanup_session()

    print("[cleanup] result:")
    import json
    print(json.dumps(result, indent=2, default=str))

    await supa.close()


if __name__ == "__main__":
    asyncio.run(main())
