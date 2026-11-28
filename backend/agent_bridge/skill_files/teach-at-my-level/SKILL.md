---
name: teach-at-my-level
description: Explain a topic, paper or piece of code pitched at what the user already knows, using their GraphRecall knowledge graph. Use when the user asks you to explain, teach or walk them through something, or before summarizing a paper for them.
metadata:
  graphrecall-scopes: read:knowledge
---

# Teach at my level

The user keeps a personal knowledge graph in GraphRecall: concepts they've studied, how well they
know each one (mastery 0-1 from their reviews), and how the concepts link. Use it so you don't
re-explain what they know or skip what they don't.

## Steps

1. **Name the concepts.** From the question (or the paper, or the code), list the 3-10 concepts
   the explanation depends on, foundations included. Use plain names ("softmax", "KV cache").
2. **Get a teaching plan.** Call `get_knowledge_frontier` with `query` set to the user's question
   and `concept_names` set to your list. It returns `teaching_plan` (ordered steps, foundations
   first, each marked teach or refresh, with a reason) and the concepts you can assume.
   If you only need a yes/no on a few names, `assess_concepts` is cheaper.
3. **Follow the plan.**
   - *strong / assume*: use the term without defining it. At most a half-sentence reminder.
   - *shaky / refresh*: one or two sentences that re-anchor it, then build on it.
   - *seen (studied, untested)*: treat as shaky.
   - *unexposed / gap*: introduce from scratch, with an example, before using it.
   - *misconceptions*: if the plan lists one, address it head-on.
4. **Connect to what they know.** Where a new idea resembles an anchor concept, say so ("this is
   the same trick as X, which you know").
5. **Close the loop** (only if the `record_exposure` tool is available to you): for each concept you
   actually taught or refreshed, call `record_exposure` with `concept`, a one-line `context`
   ("explained in a chat about transformers"), and `create_if_missing: true` for concepts that were
   new to them. This adds evidence without overwriting their tested mastery. If the user went off on a tangent worth coming back to,
   `suggest_for_later` queues it in their feed.

## Don'ts

- Don't tell the user their mastery scores unless they ask; just pitch the explanation right.
- Don't invent prerequisites the graph doesn't support to look thorough. If the graph has nothing
  on the topic, say it's new to them and teach it from the ground up.
