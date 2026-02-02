"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aria.api.routes import files, search, stats, ui, validate
from aria.common import get_logger, setup_logging


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()
    logger = get_logger(__name__)

    app = FastAPI(
        title="Aria API",
        description="API for browsing and searching the Aria vector database",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(ui.router, tags=["UI"])
    app.include_router(search.router, prefix="/api", tags=["Search"])
    app.include_router(files.router, prefix="/api", tags=["Files"])
    app.include_router(stats.router, prefix="/api", tags=["Statistics"])
    app.include_router(validate.router, prefix="/api", tags=["Validation"])

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    logger.info("Aria API initialized")
    return app


# Create default app instance
app = create_app()
