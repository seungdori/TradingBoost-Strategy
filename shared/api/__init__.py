"""
Shared API Components

Provides reusable API components including health check endpoints
and common middleware.
"""

from shared.api.health import router as health_router

__all__ = ["health_router"]
