"""
API route modules.
"""

from src.api.routes.approvals import router as approvals_router
from src.api.routes.auth import router as auth_router
from src.api.routes.health import router as health_router
from src.api.routes.tickets import router as tickets_router
from src.api.routes.webhooks import router as webhooks_router

__all__ = [
    "approvals_router",
    "auth_router",
    "health_router",
    "tickets_router",
    "webhooks_router",
]
