# Retrieval eval (golden.r4.jsonl, n=171)

| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| vector | 0.170 | 0.448 [0.38, 0.51] | 0.579 | 0.608 | 0.445 | 0.443 [0.38, 0.50] |
| keyword | 0.073 | 0.284 [0.23, 0.34] | 0.432 | 0.480 | 0.294 | 0.289 [0.25, 0.33] |
| graph | 0.177 | 0.379 [0.31, 0.45] | 0.479 | 0.503 | 0.397 | 0.386 [0.32, 0.45] |
| rrf_vk | 0.169 | 0.337 [0.28, 0.39] | 0.375 | 0.573 | 0.425 | 0.336 [0.29, 0.39] |
| rrf_vkg | 0.198 | 0.357 [0.30, 0.41] | 0.391 | 0.591 | 0.452 | 0.357 [0.30, 0.41] |
| shipped_top5 | 0.173 | 0.360 [0.31, 0.42] | 0.360 | 0.596 | 0.432 | 0.330 [0.28, 0.38] |
| ablate_vkg_no_parent_cap | 0.198 | 0.441 [0.38, 0.51] | 0.592 | 0.626 | 0.466 | 0.461 [0.40, 0.52] |
| ablate_vg | 0.181 | 0.339 [0.28, 0.40] | 0.384 | 0.556 | 0.423 | 0.342 [0.29, 0.40] |
| ablate_vg_no_parent_cap | 0.181 | 0.418 [0.35, 0.48] | 0.594 | 0.573 | 0.443 | 0.448 [0.38, 0.51] |

Difference vs vector (paired, 95% CI):

- keyword: recall@5 -0.164 [-0.228, -0.104], nDCG@10 -0.155 [-0.212, -0.099]
- graph: recall@5 -0.069 [-0.107, -0.031], nDCG@10 -0.057 [-0.094, -0.021]
- rrf_vk: recall@5 -0.111 [-0.163, -0.064], nDCG@10 -0.107 [-0.149, -0.068]
- rrf_vkg: recall@5 -0.091 [-0.139, -0.043], nDCG@10 -0.086 [-0.126, -0.048]
- shipped_top5: recall@5 -0.088 [-0.139, -0.040], nDCG@10 -0.113 [-0.149, -0.080]
- ablate_vkg_no_parent_cap: recall@5 -0.007 [-0.052, +0.033], nDCG@10 +0.017 [-0.015, +0.047]
- ablate_vg: recall@5 -0.109 [-0.153, -0.064], nDCG@10 -0.101 [-0.131, -0.072]
- ablate_vg_no_parent_cap: recall@5 -0.030 [-0.061, -0.003], nDCG@10 +0.004 [-0.013, +0.022]

By question type (recall@5 / nDCG@10):

- Complex Reasoning (n=57): vector 0.35/0.39, keyword 0.27/0.29, graph 0.33/0.38, rrf_vk 0.33/0.32, rrf_vkg 0.34/0.35, shipped_top5 0.34/0.31, ablate_vkg_no_parent_cap 0.42/0.45, ablate_vg 0.26/0.30, ablate_vg_no_parent_cap 0.34/0.41
- Contextual Summarize (n=54): vector 0.40/0.38, keyword 0.21/0.22, graph 0.34/0.35, rrf_vk 0.26/0.27, rrf_vkg 0.28/0.28, shipped_top5 0.28/0.25, ablate_vkg_no_parent_cap 0.37/0.38, ablate_vg 0.30/0.31, ablate_vg_no_parent_cap 0.37/0.41
- Fact Retrieval (n=60): vector 0.58/0.55, keyword 0.36/0.35, graph 0.47/0.43, rrf_vk 0.41/0.41, rrf_vkg 0.44/0.44, shipped_top5 0.46/0.42, ablate_vkg_no_parent_cap 0.52/0.54, ablate_vg 0.45/0.41, ablate_vg_no_parent_cap 0.53/0.52

Questions with any graph seed: 162/171
