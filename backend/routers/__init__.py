"""API Routers for GraphRecall."""

from backend.routers.feed import router as feed_router
from backend.routers.review import router as review_router
from backend.routers.chat import router as chat_router
from backend.routers.graph3d import router as graph3d_router
from backend.routers.uploads import router as uploads_router

__all__ = [
    "feed_router",
    "review_router",
    "chat_router",
    "graph3d_router",
    "uploads_router",
]
