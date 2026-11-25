"""Per-user embedding cache: hits skip the API, misses are embedded and stored."""
from unittest.mock import AsyncMock, patch

from backend.services.ingestion import embedding_service as es

OWNER = "03fc4f19-f724-433e-96cf-7956f429f6d5"


class FakePG:
    def __init__(self):
        self.rows = {}

    async def execute_query(self, q, p):
        return [{"key": k, "embedding": self.rows[k]} for k in p["keys"] if k in self.rows]

    async def execute_update(self, q, p):
        self.rows[p["k"]] = p["e"]


async def test_second_embed_of_same_text_hits_cache():
    pg = FakePG()
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder, svc.dims = object(), 4
    calls = []

    async def fake_uncached(texts):
        calls.append(list(texts))
        return [[float(len(t))] * 4 for t in texts]

    svc._embed_uncached = fake_uncached
    with patch("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=pg)):
        a = await svc.embed_batch(["alpha", "beta"], owner=OWNER)
        b = await svc.embed_batch(["beta", "gamma"], owner=OWNER)
    assert calls == [["alpha", "beta"], ["gamma"]]
    assert a[1] == b[0] == [4.0] * 4


async def test_no_owner_or_non_uuid_owner_bypasses_cache():
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder, svc.dims = object(), 4
    svc._embed_uncached = AsyncMock(return_value=[[1.0] * 4])
    with patch("backend.db.postgres_client.get_postgres_client", AsyncMock(side_effect=AssertionError("no db"))):
        assert await svc.embed_batch(["x"]) == [[1.0] * 4]
        assert await svc.embed_batch(["x"], owner="default_user") == [[1.0] * 4]
