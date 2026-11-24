"""JSON serialization for everything the bridge returns (REST, SSE, MCP).

Timestamps are always ISO 8601 with a ``T`` separator and an explicit UTC offset
(``2026-11-24T06:11:10.751395+00:00``), which is what iOS ``ISO8601DateFormatter`` /
``JSONDecoder.dateDecodingStrategy = .iso8601`` (with fractional seconds) expects.
``str(datetime)`` gives ``2026-11-24 06:11:10+00:00`` (space), which breaks decoding.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID


def iso(v: Any) -> Any:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)  # DB columns are TIMESTAMPTZ (UTC)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return iso(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    return obj
