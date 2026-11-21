"""NeuroFeed modular ranking engine for GraphRecall."""

from backend.feed_ranker.graph_signals import (
    GraphSignalsProtocol,
    InMemoryGraphSignals,
    NullGraphSignals,
    load_graph_signals,
)
from backend.feed_ranker.mmr import mmr_select, pool_centered_cosine_matrix
from backend.feed_ranker.ranker import FeedRanker
from backend.feed_ranker.scoring import (
    compute_backtrack_targets,
    compute_fire_leverage,
    score_fsrs_candidate,
)
from backend.feed_ranker.types import CandidateCard, RankedCard, RankerConfig

__all__ = [
    "CandidateCard",
    "FeedRanker",
    "GraphSignalsProtocol",
    "InMemoryGraphSignals",
    "NullGraphSignals",
    "RankedCard",
    "RankerConfig",
    "compute_backtrack_targets",
    "compute_fire_leverage",
    "load_graph_signals",
    "mmr_select",
    "pool_centered_cosine_matrix",
    "score_fsrs_candidate",
]
