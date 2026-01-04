"""
API route modules.
"""

from src.api.routes.health import router as health_router
from src.api.routes.tickets import router as tickets_router

__all__ = ["health_router", "tickets_router"]
