"""Which intents actually change what the chat graph does.

``get_context_node`` / ``generate_response_node`` branch on: path (3-hop prerequisite expansion),
explain (1 hop), summarize (community map step), show_images (more chunks + image retrieval) and
quiz (proactive quiz generation). compare, find and general all take the default path (2 hops),
so confusing them with each other costs nothing. Routing accuracy is measured on these groups.
"""
ROUTE_GROUP: dict[str, str] = {
    "path": "path",
    "explain": "explain",
    "summarize": "summarize",
    "show_images": "show_images",
    "quiz": "quiz",
    "compare": "default",
    "find": "default",
    "general": "default",
}
