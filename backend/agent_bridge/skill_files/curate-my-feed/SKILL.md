---
name: curate-my-feed
description: Propose articles, papers and flashcards for the user's GraphRecall feed based on what they're learning and where their gaps are. Use when the user asks you to find reading for them, build a study plan, or set up today's digest.
metadata:
  graphrecall-scopes: read:knowledge write:feed
---

# Curate my feed

Everything you propose stays **pending** until the user approves it in the app, so propose a few
good items rather than many.

## Steps

1. **Find the target.** Call `get_recent_activity` (last 7 days) to see what they're working on,
   then `get_knowledge_frontier` with that topic as `query` to get their frontier (shaky) and gaps
   (unseen). Aim items at the frontier: things they've started but haven't consolidated.
2. **Find material** with your own search tools. Prefer primary sources, well-known explainers and
   papers. Check every link loads; never propose a URL you haven't seen.
3. **Propose** with `propose_feed_items`. For each item: `title`; a `summary` in your own words
   (never pasted text); a `reason` tied to their graph ("you've reviewed attention but not KV
   caching, which this builds on"); `source_url`; `item_kind` (article, flashcard, mcq, note);
   `concept_ids` from `search_concepts` where you can; and an `idempotency_key` so re-running
   doesn't create duplicates. A flashcard item takes `flashcard: {front, back}`.
4. **Optionally group them** into a day's digest with `schedule_daily_digest` (`title`, a short
   `summary`, and the `item_ids` the proposal returned).
5. For things worth reading later rather than today, use `suggest_for_later` with `when`
   ("this weekend", "in 3 days").
6. Tell the user what you proposed and that it's waiting for their approval in the app.
