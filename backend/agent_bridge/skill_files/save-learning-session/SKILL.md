---
name: save-learning-session
description: Save what the user learned in this conversation into their GraphRecall knowledge graph - the topic, key details, what they understood, what they struggled with, and every article, paper or video used - as one background import. Use when the user says to save, remember or ingest this session, or when a learning conversation is wrapping up (offer first).
metadata:
  graphrecall-scopes: read:knowledge write:ingest
---

# Save this learning session

GraphRecall turns what you send into a session note, imports each resource (concepts, flashcards,
search), and records what the user struggled with so their reviews come back to it sooner. It runs
in the background, so the conversation can carry on.

## 1. Gather it from the conversation

- **topic**: one line ("KV caching in transformer inference").
- **learned**: concepts the user showed they understood: they explained it back, applied it, or
  answered a question about it correctly. Not everything that was mentioned. Plain names, 3-15 items.
- **struggled**: concepts they got wrong, asked about repeatedly, or said were confusing, each with a
  one-sentence `why` ("mixed up keys and values"; "didn't see why the cache grows with sequence
  length"). This is the most valuable part, so be specific and honest.
- **summary_markdown**: the key details worth keeping, in your own words: definitions, the
  intuition that made it click, formulas, small examples, gotchas, and open questions. Use headings
  and bullets; about 300-1500 words. This is what they'll reread, so make it self-contained.
- **resources**: every article, paper, doc page and video the session used or that you
  recommended and they opened, as `{url, title, note}`. `note` says what it was for. Only real URLs
  you saw; never invent one. YouTube videos are imported too (from captions, or watched by Gemini
  when there are none); videos on other sites are listed in the note but not imported.
- **transcript**: leave it out unless the user asks. A distilled summary ingests far better than a
  raw chat, and anything over 30,000 characters is cut.

Leave out secrets, credentials and personal details that aren't about the topic.

## 2. Confirm before saving

Show the user a short preview (topic, the learned and struggled lists, the resource titles) and ask
before calling. Everything goes straight into their graph, with no approval step in the app.

## 3. Save

Call `save_learning_session`. With task support, the client tracks it; otherwise you get a
`task_id`, and you poll `get_ingest_status` every 20-30 seconds or check back later. A session with
several resources takes a few minutes.

## 4. Report

When it completes, say in two or three lines what was saved: the note, how many resources were
imported (and which were duplicates or skipped, and why), and which struggles were recorded. If
some concepts came back under `not_in_graph`, mention that they'll be picked up as the notes are
processed.

For a single article outside a session, use `ingest_link` instead.
