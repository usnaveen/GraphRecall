"""create_concept against a real Neo4j: merge decisions that point at an existing concept id.

Runs only when a Neo4j is reachable (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD); skipped otherwise.
Each test uses its own user_id and deletes its nodes afterwards.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _client():
    from neo4j import AsyncGraphDatabase

    from backend.db.neo4j_client import Neo4jClient

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
    try:
        driver = AsyncGraphDatabase.driver(uri, auth=auth)
        await driver.verify_connectivity()
        await driver.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Neo4j at {uri}: {exc}")
    client = Neo4jClient()
    await client.initialize()
    return client


@pytest.fixture
async def neo4j_and_user():
    client = await _client()
    user_id = f"test-merge-{uuid.uuid4()}"
    yield client, user_id
    await client.execute_query("MATCH (c:Concept {user_id: $u}) DETACH DELETE c", {"u": user_id})
    await client.close()


def _node(result):
    return result["c"]


async def test_merge_into_existing_id_under_a_different_name(neo4j_and_user):
    neo4j, user_id = neo4j_and_user
    first = _node(await neo4j.create_concept(
        name="Non-small cell lung cancer", definition="Most common lung cancer.", domain="Oncology",
        complexity_score=5, user_id=user_id, embedding=[0.1] * 768))

    # What user_review_node produces for a "merge" decision: new name, existing id.
    merged = _node(await neo4j.create_concept(
        name="NSCLC", definition="Lung cancer type that is not small cell, about 85% of cases.", domain="Oncology",
        complexity_score=6, user_id=user_id, concept_id=first["id"]))

    assert merged["id"] == first["id"]
    assert merged["name"] == "Non-small cell lung cancer"          # canonical name kept
    assert merged["definition"].startswith("Lung cancer type")      # longer definition wins
    assert merged["embedding"] is not None                          # not wiped by an embedding-less call
    rows = await neo4j.execute_query("MATCH (c:Concept {user_id: $u}) RETURN count(c) AS n", {"u": user_id})
    assert rows[0]["n"] == 1


async def test_rementioned_concept_keeps_its_embedding(neo4j_and_user):
    neo4j, user_id = neo4j_and_user
    await neo4j.create_concept(name="Biopsy", definition="Tissue sample.", domain="Oncology",
                               complexity_score=3, user_id=user_id, embedding=[0.2] * 768)
    again = _node(await neo4j.create_concept(name="Biopsy", definition="Removal of tissue for testing.",
                                             domain="Oncology", complexity_score=3, user_id=user_id))
    assert again["embedding"] is not None


async def test_unknown_id_still_creates_by_name(neo4j_and_user):
    neo4j, user_id = neo4j_and_user
    made = _node(await neo4j.create_concept(name="Staging", definition="Extent of cancer.", domain="Oncology",
                                            complexity_score=4, user_id=user_id, concept_id=str(uuid.uuid4())))
    assert made["name"] == "Staging"
