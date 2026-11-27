# Retrieval eval (golden.h1.jsonl, n=142)

| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| vector | 0.269 | 0.603 [0.53, 0.67] | 0.706 | 0.739 | 0.590 | 0.577 [0.52, 0.64] |
| keyword | 0.149 | 0.408 [0.34, 0.48] | 0.543 | 0.549 | 0.400 | 0.394 [0.34, 0.45] |
| graph | 0.199 | 0.484 [0.41, 0.56] | 0.533 | 0.577 | 0.456 | 0.449 [0.38, 0.52] |
| rrf_vk | 0.274 | 0.430 [0.37, 0.49] | 0.473 | 0.669 | 0.581 | 0.446 [0.39, 0.50] |
| rrf_vkg | 0.279 | 0.442 [0.38, 0.50] | 0.466 | 0.690 | 0.571 | 0.440 [0.38, 0.49] |
| shipped_top5 | 0.333 | 0.642 [0.58, 0.71] | 0.642 | 0.817 | 0.662 | 0.590 [0.53, 0.65] |
| ablate_vkg_no_parent_cap | 0.253 | 0.607 [0.54, 0.67] | 0.728 | 0.739 | 0.571 | 0.576 [0.52, 0.64] |
| ablate_vg | 0.210 | 0.375 [0.32, 0.44] | 0.466 | 0.627 | 0.497 | 0.391 [0.34, 0.44] |
| ablate_vg_no_parent_cap | 0.210 | 0.524 [0.45, 0.60] | 0.667 | 0.627 | 0.500 | 0.511 [0.45, 0.58] |

Difference vs vector (paired, 95% CI):

- keyword: recall@5 -0.196 [-0.267, -0.132], nDCG@10 -0.183 [-0.241, -0.129]
- graph: recall@5 -0.120 [-0.188, -0.051], nDCG@10 -0.128 [-0.186, -0.075]
- rrf_vk: recall@5 -0.173 [-0.234, -0.113], nDCG@10 -0.131 [-0.178, -0.087]
- rrf_vkg: recall@5 -0.161 [-0.225, -0.097], nDCG@10 -0.137 [-0.185, -0.090]
- shipped_top5: recall@5 +0.039 [-0.014, +0.089], nDCG@10 +0.013 [-0.032, +0.056]
- ablate_vkg_no_parent_cap: recall@5 +0.004 [-0.050, +0.060], nDCG@10 -0.001 [-0.042, +0.038]
- ablate_vg: recall@5 -0.228 [-0.291, -0.167], nDCG@10 -0.187 [-0.226, -0.147]
- ablate_vg_no_parent_cap: recall@5 -0.079 [-0.141, -0.017], nDCG@10 -0.066 [-0.107, -0.026]

By question type (recall@5 / nDCG@10):

- Complex Reasoning (n=44): vector 0.55/0.54, keyword 0.37/0.39, graph 0.56/0.49, rrf_vk 0.39/0.40, rrf_vkg 0.42/0.41, shipped_top5 0.61/0.55, ablate_vkg_no_parent_cap 0.64/0.59, ablate_vg 0.37/0.40, ablate_vg_no_parent_cap 0.58/0.54
- Contextual Summarize (n=43): vector 0.53/0.52, keyword 0.32/0.33, graph 0.39/0.40, rrf_vk 0.36/0.38, rrf_vkg 0.39/0.37, shipped_top5 0.55/0.49, ablate_vkg_no_parent_cap 0.48/0.49, ablate_vg 0.36/0.35, ablate_vg_no_parent_cap 0.43/0.45
- Fact Retrieval (n=55): vector 0.70/0.65, keyword 0.51/0.44, graph 0.49/0.45, rrf_vk 0.51/0.53, rrf_vkg 0.50/0.51, shipped_top5 0.74/0.70, ablate_vkg_no_parent_cap 0.69/0.63, ablate_vg 0.39/0.42, ablate_vg_no_parent_cap 0.55/0.54

Questions with any graph seed: 138/142
