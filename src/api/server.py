"""
FastAPI application server.

Main entry point for the Enterprise AI Platform API.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import health_router, tickets_router
from src.core.config import get_settings
from src.db.connection import close_pool, create_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    settings = get_settings()

    # Initialize database pool
    try:
        await create_pool()
        # Log without exposing credentials
        db_host = settings.database_url.split("@")[-1].split("/")[0] if "@" in settings.database_url else "localhost"
        print(f"Database pool initialized: connected to {db_host}")
    except Exception as e:
        print(f"Warning: Database connection failed: {type(e).__name__}")
        print("Running without database - audit logs will be skipped")

    yield

    # Shutdown
    await close_pool()
    print("Database pool closed")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app
    """
    settings = get_settings()

    app = FastAPI(
        title="Good AI Enterprise Reference",
        description="""
        Enterprise AI Platform Reference Implementation with Trust Layer.

        ## Features

        - **Trust Layer**: LLM Gateway + Policy Engine + Audit Log
        - **PII Redaction**: Automatic tokenization of sensitive data
        - **Policy Engine**: RBAC and severity-based approval workflows
        - **Audit Logging**: Immutable compliance records

        ## Authentication

        All endpoints require authentication headers:
        - `X-User-Id`: User identifier
        - `X-Tenant-Id`: Tenant/organization identifier
        - `X-Roles`: Comma-separated list of roles

        ## Demo Agent: Ticket Triage

        The `/tickets/triage` endpoint demonstrates:
        1. PII redaction before LLM processing
        2. AI-powered severity classification
        3. Policy-gated response generation
        4. Audit logging for compliance

        ---

        **Maintainer**: Roger Simões @ [Good AI](https://wearegoodai.com)
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(tickets_router)

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
