from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic goes here later.
    # Example: initialize database connections, AI clients, etc.

    yield

    # Shutdown logic goes here later.
    # Example: close database connections.


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Nirnaya — AI-powered data analytics backend.",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)


app.include_router(
    health_router,
    prefix=settings.api_v1_prefix,
)


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {
        "service": "Nirnaya API",
        "status": "running",
    }