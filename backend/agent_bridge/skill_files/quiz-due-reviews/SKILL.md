---
name: quiz-due-reviews
description: Run a short spaced-repetition quiz in chat on the concepts that are due for review in the user's GraphRecall graph. Use when the user asks to be quizzed, wants to review or revise, or asks what they should study now.
metadata:
  graphrecall-scopes: read:knowledge
---

# Quiz my due reviews

## Steps

1. Call `list_due_reviews` (limit 5-10). If nothing is due, call `get_knowledge_profile` and offer
   to quiz the weakest concepts it lists instead.
2. For each concept, one at a time:
   - If you need more than the name and definition to ask a good question, call
     `get_concept_neighborhood` with its `concept_id` to see what it links to.
   - Ask **one** question that needs recall or reasoning, not recognition: "why", "what breaks if",
     "how does it differ from <linked concept>". No multiple choice unless the user asks.
   - Wait for the answer. Then say what was right, what was missing, and give the short correct
     answer. Keep it to a few lines.
3. After the last question, summarize: which concepts were solid, which were shaky, and one thing to
   reread for each shaky one.
4. If the `record_exposure` tool is available, record each concept you quizzed with `context` like
   "quizzed in chat: answered well" or "quizzed in chat: missed the role of X".

## Be honest about what this does

A chat quiz does **not** update their review schedule or mastery scores: only reviews done in the
GraphRecall app do. Say so once at the end, and suggest they clear the due cards in the app.
