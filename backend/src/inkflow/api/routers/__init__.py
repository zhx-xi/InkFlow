"""FastAPI 路由模块."""

from inkflow.api.routers.context import router as context_router
from inkflow.api.routers.extractions import router as extractions_router
from inkflow.api.routers.foreshadowings import router as foreshadowings_router
from inkflow.api.routers.timeline import router as timeline_router

__all__ = ["context_router", "extractions_router", "foreshadowings_router", "timeline_router"]
