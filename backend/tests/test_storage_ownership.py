"""GR-SEC-02: a user can only delete their own stored objects (uploads/{user_id}/...)."""

import pytest

from backend.services.storage_service import StorageService

pytestmark = pytest.mark.asyncio

BASE = "https://files.example.com"
ALICE, BOB = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


class FakeS3:
    def __init__(self, keys=()):
        self.deleted, self.keys = [], list(keys)

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)

    def get_paginator(self, _name):
        keys = self.keys

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, Bucket, Delete):
        self.deleted += [o["Key"] for o in Delete["Objects"]]


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("R2_PUBLIC_URL_BASE", BASE)
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path))
    for k in ("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = StorageService()
    s.s3_client = FakeS3([f"uploads/{ALICE}/1_a.png", f"uploads/{ALICE}/2_orphan.pdf", f"uploads/{BOB}/1_b.png"])
    return s


async def test_owner_can_delete_own_file(storage):
    assert await storage.delete_file(f"{BASE}/uploads/{ALICE}/1_a.png", owner_id=ALICE)
    assert storage.s3_client.deleted == [f"uploads/{ALICE}/1_a.png"]


@pytest.mark.parametrize("url", [
    f"{BASE}/uploads/{BOB}/1_b.png",                       # another user's object
    f"{BASE}/uploads/{ALICE}/../{BOB}/1_b.png",            # climbing out of the prefix
    f"{BASE}/uploads/{ALICE}",                             # the prefix itself without the slash
    f"{BASE}/backups/db.sql.gz",                           # anything outside uploads/
])
async def test_cannot_delete_other_objects(storage, url):
    assert not await storage.delete_file(url, owner_id=ALICE)
    assert storage.s3_client.deleted == []


def test_foreign_bucket_urls_are_detected(storage):
    assert storage.is_other_users_object(f"{BASE}/uploads/{BOB}/1_b.png", ALICE)
    assert not storage.is_other_users_object(f"{BASE}/uploads/{ALICE}/1_a.png", ALICE)
    assert not storage.is_other_users_object("https://elsewhere.example/pic.png", ALICE)  # external link


async def test_prefix_delete_removes_only_that_user_including_orphans(storage):
    n = await storage.delete_user_prefix(ALICE)
    assert n == 2
    assert sorted(storage.s3_client.deleted) == [f"uploads/{ALICE}/1_a.png", f"uploads/{ALICE}/2_orphan.pdf"]


async def test_local_fallback_respects_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path))
    for k in ("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = StorageService()
    bob_file = tmp_path / "uploads" / BOB / "b.png"
    bob_file.parent.mkdir(parents=True)
    bob_file.write_bytes(b"x")
    assert not await s.delete_file(bob_file.as_uri(), owner_id=ALICE)
    assert bob_file.exists()
    assert await s.delete_file(bob_file.as_uri(), owner_id=BOB)
    assert not bob_file.exists()
