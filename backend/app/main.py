import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.gemini_status import router as gemini_status_router
from app.core.config import get_settings
from app.core.key_manager import init_pools


# ---------------------------------------------------------------------------
# Logging — configured once at module load, before anything else runs
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (modern handler — replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise key pools and log counts.
    Shutdown: log a goodbye message.
    The app starts normally even when NO keys are configured.
    """
    settings = get_settings()
    logger.info(
        "[%s] Starting up — environment: %s",
        settings.PROJECT_NAME, settings.ENVIRONMENT,
    )

    # Initialise key pools (idempotent; logs counts + warnings internally)
    await init_pools()

    # Log a summary of configured key counts for each domain
    from app.core.key_manager import _pools
    for domain, pool in _pools.items():
        if pool.size == 0:
            logger.warning(
                "[Startup] Domain=%s has 0 keys — calls will fail until keys are configured.",
                domain,
            )
        else:
            logger.info("[Startup] Domain=%s → %d key(s) ready.", domain, pool.size)

    yield

    logger.info("[%s] Shutting down.", settings.PROJECT_NAME)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="AI agent backend for Pakistani farmers.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # -------------------------------------------------------------------
    # CORS — allow all origins for development.
    # TODO (Stage 9 / production): replace ["*"] with the specific origin
    # list of your deployed frontend and remove allow_credentials=False.
    # -------------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    application.include_router(health_router)
    application.include_router(gemini_status_router)

    @application.get("/", tags=["Root"])
    async def root() -> dict:
        return {"project": "FarmAI", "status": "running"}

    return application


app = create_app()
