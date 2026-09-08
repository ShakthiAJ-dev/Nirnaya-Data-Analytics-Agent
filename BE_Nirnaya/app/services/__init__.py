"""
app/services/__init__.py
------------------------
Central registry for Nirnaya service singletons and factories.

  • SupabaseService  — singleton on app.state (initialised in lifespan)
  • RedisService     — singleton on app.state (initialised in lifespan)
  • LLMService       — per-request factory (NOT a singleton, NOT on app.state)
  • DataService      — per-request factory (session-scoped DB + Storage ops)
"""

from app.services.data_service import DataService, FileService, TableService
from app.services.database_service import DatabaseService
from app.services.llm_service import LLMService
from app.services.project_service import ProjectService
from app.services.redis_service import RedisService
from app.services.session_service import SessionService
from app.services.supabase_service import SupabaseService
from app.services.ws_manager import WSManager

__all__ = [
    "DataService",
    "DatabaseService",
    "FileService",
    "LLMService",
    "ProjectService",
    "SessionService",
    "SupabaseService",
    "RedisService",
    "TableService",
    "WSManager",
]

