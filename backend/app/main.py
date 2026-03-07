import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api.routes import all_routers

logger = logging.getLogger("carfinda")


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared services on startup; tear them down on shutdown."""
    settings = get_settings()
    logger.info("CarFINDa API starting (env=%s)", settings.ENVIRONMENT)

    # TODO: Initialise Supabase client
    # TODO: Initialise async DB engine / session factory
    # TODO: Initialise Gemini client
    # TODO: Warm up any caches

    yield

    # TODO: Close DB connections, HTTP clients, etc.
    logger.info("CarFINDa API shutting down")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CarFINDa API",
    description="Car finding and scoring platform backend",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

settings = get_settings()

# CORS — allow all origins in development; restrict in production
_allowed_origins = ["*"] if settings.ENVIRONMENT == "development" else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def supabase_auth_middleware(request: Request, call_next):
    """Stub auth middleware.

    For paths that don't require auth (/health, /docs, /openapi.json)
    the request passes through. For all /api/* paths the
    ``get_current_user`` dependency handles JWT validation at the
    route level, so this middleware currently just logs and passes through.

    TODO: Wire in real Supabase JWT verification at the middleware level
    if blanket auth is preferred over per-route dependencies.
    """
    # Let non-API and docs routes through without any auth check
    if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
        return await call_next(request)

    # For /api/* routes, auth is enforced via the get_current_user dependency.
    # This middleware can be expanded later for rate-limiting, logging, etc.
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

for router in all_routers:
    app.include_router(router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health_check():
    """Simple liveness probe."""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
    }
