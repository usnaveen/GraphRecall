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
# The card the image sits on is #141418; a matching, empty background makes it sit cleanly.
STYLE = (
    "Clean, minimal educational illustration for a flashcard in a dark app. Flat vector style. "
    "The background must be one solid, empty colour, #141418, filling the whole image edge to edge: "
    "no frame, border, vignette, gradient, texture or drop shadow. Neon lime (#B6FF2E) and cyan "
    "(#2EFFE6) for the key elements, soft white for secondary lines. Show the mechanism, not "
    "decoration. At most a few short labels, spelled correctly; no paragraphs of text."
)


async def generate(client: httpx.AsyncClient, key: str, concept: str,
                   reference: tuple[bytes, str, str] | None = None) -> bytes:
    """`reference` = (image bytes, mime, source title): a real figure to redraw in our style."""
    parts: list[dict] = []
    if reference:
        data, mime, source = reference
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
        prompt = (f"{STYLE}\n\nConcept: {concept}. The attached figure is from \"{source}\". Redraw it "
                  f"faithfully (same structure, components and labels) in this style.")
    else:
        prompt = f"{STYLE}\n\nConcept: {concept}. Draw the one picture that makes this concept click."
    parts.append({"text": prompt})
    r = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}},
        timeout=150,
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
    ap.add_argument("--replace", action="store_true", help="regenerate concepts that already have one")
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
        from backend.services.concept_figures import best_figure

        # Real figures from the user's own sources, used as references when one is about the concept.
        real = [dict(r) for r in await db.fetch(
            "SELECT f.id, f.page, f.label, f.caption, f.width, f.height, n.title AS source_title "
            "FROM source_figures f JOIN notes n ON n.id = f.note_id "
            "WHERE f.user_id = $1::uuid AND n.title <> $2", args.user, NOTE_TITLE)]
        made = 0
        async with httpx.AsyncClient() as client:
            for concept in args.concepts:
                caption = f"{concept}, illustrated."
                existing = await db.fetchval(
                    "SELECT id FROM source_figures WHERE user_id = $1::uuid AND note_id = $2 AND caption = $3",
                    args.user, note_id, caption)
                if existing and not args.replace:
                    print(f"skip  {concept} (already illustrated)")
                    continue
                ref_fig = best_figure(concept, real)
                reference = None
                if ref_fig is not None:
                    row = await db.fetchrow("SELECT image, mime FROM source_figures WHERE id = $1", ref_fig["id"])
                    reference = (bytes(row["image"]), row["mime"] or "image/png", ref_fig["source_title"])
                try:
                    jpeg, w, h = shrink(await generate(client, key, concept, reference))
                except Exception as e:  # noqa: BLE001 - report and carry on with the next concept
                    print(f"FAIL  {concept}: {e}")
                    continue
                if existing:
                    await db.execute(
                        "UPDATE source_figures SET image = $2, width = $3, height = $4 WHERE id = $1",
                        existing, jpeg, w, h)
                    made += 1
                    print(f"redo  {concept} ({w}x{h}){' from ' + reference[2] if reference else ''}")
                    continue
                await db.execute(
                    "INSERT INTO source_figures (user_id, note_id, page, label, caption, mime, image, width, height) "
                    "VALUES ($1::uuid, $2, 0, $7, $3, 'image/jpeg', $4, $5, $6)",
                    args.user, note_id, caption, jpeg, w, h, f"Illustration: {concept}")
                made += 1
                print(f"made  {concept} ({w}x{h}, {len(jpeg) // 1024} KB){' from ' + reference[2] if reference else ''}")
        print(f"done: {made} new illustrations under note {note_id}")
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
