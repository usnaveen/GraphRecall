"""Generate Nano Banana (Gemini image) illustrations for concepts and attach them to concept cards.

Concept cards already show a figure from the user's own sources when one matches the concept
(backend/services/concept_figures.py). This script makes one illustration per named concept with
a Gemini image model and stores it the same way: a `source_figures` row under one clearly labelled
note, "Concept illustrations (Gemini)". The card shows it with that source title, so a generated
picture is never mistaken for a figure from the user's own books.

Idempotent: a concept that already has a generated illustration is skipped.

    python -m backend.scripts.generate_concept_illustrations --user <uuid> "Self-Attention" "KV Cache"

Needs GOOGLE_API_KEY with billing (image models have no free quota) and DATABASE_URL.
Costs roughly one image-model call per concept.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import sys

import httpx

NOTE_TITLE = "Concept illustrations (Gemini)"
MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
STYLE = (
    "Clean, minimal educational illustration for a flashcard. Flat vector style on a near-black "
    "background (#0a0a0f) with lime (#B6FF2E) and cyan (#2EFFE6) accents. Show the mechanism, not "
    "decoration. Use at most a few short labels, spelled correctly; no paragraphs of text."
)


async def generate(client: httpx.AsyncClient, key: str, concept: str) -> bytes:
    prompt = f"{STYLE}\n\nConcept: {concept}. Draw the one picture that makes this concept click."
    r = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE"]}},
        timeout=120,
    )
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{data['error'].get('status')}: {data['error'].get('message', '')[:160]}")
    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError("no image in response")


def shrink(raw: bytes) -> tuple[bytes, int, int]:
    """The model returns a compact JPEG already; keep it and read its size from the SOF marker."""
    buf = io.BytesIO(raw)
    if buf.read(2) != b"\xff\xd8":
        raise RuntimeError("not a JPEG")
    while True:
        marker = buf.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            raise RuntimeError("no JPEG frame header")
        length = int.from_bytes(buf.read(2), "big")
        if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
            buf.read(1)  # precision
            h = int.from_bytes(buf.read(2), "big")
            w = int.from_bytes(buf.read(2), "big")
            return raw, w, h
        buf.seek(length - 2, io.SEEK_CUR)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("concepts", nargs="+")
    args = ap.parse_args()

    import asyncpg

    key = os.environ["GOOGLE_API_KEY"]
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    db = await asyncpg.connect(dsn)
    try:
        note_id = await db.fetchval(
            "SELECT id FROM notes WHERE user_id = $1::uuid AND title = $2 LIMIT 1", args.user, NOTE_TITLE)
        if not note_id:
            note_id = await db.fetchval(
                "INSERT INTO notes (user_id, title, content_text, content_type, resource_type) "
                "VALUES ($1::uuid, $2, $3, 'markdown', 'notes') RETURNING id",
                args.user, NOTE_TITLE,
                "Illustrations generated with a Gemini image model (Nano Banana) for concept cards. "
                "Not from your own sources.",
            )
        made = 0
        async with httpx.AsyncClient() as client:
            for concept in args.concepts:
                caption = f"{concept}, illustrated."
                exists = await db.fetchval(
                    "SELECT 1 FROM source_figures WHERE user_id = $1::uuid AND note_id = $2 AND caption = $3",
                    args.user, note_id, caption)
                if exists:
                    print(f"skip  {concept} (already illustrated)")
                    continue
                try:
                    jpeg, w, h = shrink(await generate(client, key, concept))
                except Exception as e:  # noqa: BLE001 - report and carry on with the next concept
                    print(f"FAIL  {concept}: {e}")
                    continue
                await db.execute(
                    "INSERT INTO source_figures (user_id, note_id, page, label, caption, mime, image, width, height) "
                    "VALUES ($1::uuid, $2, 0, $7, $3, 'image/jpeg', $4, $5, $6)",
                    args.user, note_id, caption, jpeg, w, h, f"Illustration: {concept}")
                made += 1
                print(f"made  {concept} ({w}x{h}, {len(jpeg) // 1024} KB)")
        print(f"done: {made} new illustrations under note {note_id}")
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
