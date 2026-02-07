"""API Routers for GraphRecall."""

from backend.routers.feed import router as feed_router
from backend.routers.review import router as review_router
from backend.routers.chat import router as chat_router
from backend.routers.graph3d import router as graph3d_router
from backend.routers.uploads import router as uploads_router
from backend.routers.notes import router as notes_router
from backend.routers.concepts import router as concepts_router
from backend.routers.nodes import router as nodes_router
from backend.routers.images import router as images_router

__all__ = [
    "feed_router",
    "review_router",
    "chat_router",
    "graph3d_router",
    "uploads_router",
    "notes_router",
    "concepts_router",
    "nodes_router",
    "images_router",
]
