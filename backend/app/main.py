from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIDMiddleware


def create_app() -> FastAPI:
    configure_logging(settings.log_level, settings.log_file_path)
    logger = get_logger("nyayone.app")

    # Fail closed if registration crypto is misconfigured in prod/staging
    # (absent or the known dev default). No-op in development.
    from app.core.crypto import assert_crypto_ready

    assert_crypto_ready()

    app = FastAPI(title=settings.app_name, version=settings.app_version)

    # Request correlation ID + access logging (added first so it wraps all requests).
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Expose the correlation header so browser JS can read it cross-origin.
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    # Root liveness probe (no prefix) + versioned API surface.
    @app.get("/health", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "nyayone-backend"}

    app.include_router(api_router, prefix="/api/v1")

    logger.info("app_startup", extra={"env": settings.app_env, "version": settings.app_version})
    return app


app = create_app()
