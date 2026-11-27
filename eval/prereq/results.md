# Prerequisite-chain benchmark (n=35 human-checked links, specific prerequisites)

Question: "Explain B from the ground up, including the concepts it builds on." Does the context the model receives mention B's prerequisite A?

| arm | mentions prerequisite A | mentions B (sanity) |
|---|---|---|
| vector_top5 (plain RAG) | 0.57 | 0.97 |
| shipped_chunks | 0.51 | 0.97 |
| shipped_context (chunks + graph concepts) | 1.00 | — |

Paired difference vs vector_top5 (95% bootstrap CI):

- shipped_chunks: -0.06 [-0.20, +0.06]
- shipped_context: +0.43 [+0.26, +0.60]
