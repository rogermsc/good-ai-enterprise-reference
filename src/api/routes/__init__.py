"""
API route modules.
"""

from src.api.routes.auth import router as auth_router
from src.api.routes.health import router as health_router
from src.api.routes.tickets import router as tickets_router

__all__ = ["auth_router", "health_router", "tickets_router"]
