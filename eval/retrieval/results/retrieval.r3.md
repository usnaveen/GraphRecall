# Retrieval eval (golden.r3.jsonl, n=168)

| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| vector | 0.229 | 0.494 [0.43, 0.56] | 0.634 | 0.685 | 0.514 | 0.503 [0.45, 0.56] |
| keyword | 0.066 | 0.301 [0.25, 0.36] | 0.458 | 0.488 | 0.289 | 0.295 [0.25, 0.34] |
| graph | 0.208 | 0.423 [0.36, 0.49] | 0.506 | 0.554 | 0.417 | 0.412 [0.35, 0.47] |
| rrf_vk | 0.162 | 0.283 [0.24, 0.34] | 0.307 | 0.530 | 0.399 | 0.287 [0.24, 0.34] |
| rrf_vkg | 0.188 | 0.306 [0.26, 0.36] | 0.328 | 0.554 | 0.421 | 0.311 [0.26, 0.36] |
| shipped_top5 | 0.210 | 0.307 [0.26, 0.36] | 0.307 | 0.554 | 0.437 | 0.313 [0.26, 0.37] |
| ablate_vkg_no_parent_cap | 0.188 | 0.497 [0.44, 0.56] | 0.658 | 0.679 | 0.482 | 0.495 [0.44, 0.55] |
| ablate_vg | 0.236 | 0.335 [0.28, 0.39] | 0.356 | 0.583 | 0.470 | 0.349 [0.29, 0.40] |
| ablate_vg_no_parent_cap | 0.236 | 0.499 [0.43, 0.57] | 0.626 | 0.667 | 0.509 | 0.502 [0.45, 0.56] |

Difference vs vector (paired, 95% CI):

- keyword: recall@5 -0.193 [-0.261, -0.128], nDCG@10 -0.208 [-0.264, -0.153]
- graph: recall@5 -0.071 [-0.116, -0.028], nDCG@10 -0.091 [-0.139, -0.050]
- rrf_vk: recall@5 -0.211 [-0.273, -0.151], nDCG@10 -0.217 [-0.269, -0.167]
- rrf_vkg: recall@5 -0.188 [-0.249, -0.131], nDCG@10 -0.192 [-0.241, -0.145]
- shipped_top5: recall@5 -0.187 [-0.245, -0.131], nDCG@10 -0.190 [-0.234, -0.146]
- ablate_vkg_no_parent_cap: recall@5 +0.003 [-0.044, +0.052], nDCG@10 -0.008 [-0.044, +0.028]
- ablate_vg: recall@5 -0.159 [-0.208, -0.112], nDCG@10 -0.154 [-0.188, -0.119]
- ablate_vg_no_parent_cap: recall@5 +0.005 [-0.022, +0.031], nDCG@10 -0.001 [-0.021, +0.018]

By question type (recall@5 / nDCG@10):

- Complex Reasoning (n=57): vector 0.45/0.45, keyword 0.29/0.30, graph 0.37/0.38, rrf_vk 0.29/0.28, rrf_vkg 0.29/0.29, shipped_top5 0.30/0.31, ablate_vkg_no_parent_cap 0.48/0.46, ablate_vg 0.29/0.29, ablate_vg_no_parent_cap 0.42/0.44
- Contextual Summarize (n=51): vector 0.49/0.47, keyword 0.26/0.28, graph 0.38/0.34, rrf_vk 0.25/0.25, rrf_vkg 0.27/0.26, shipped_top5 0.25/0.25, ablate_vkg_no_parent_cap 0.46/0.47, ablate_vg 0.28/0.30, ablate_vg_no_parent_cap 0.49/0.46
- Fact Retrieval (n=60): vector 0.54/0.58, keyword 0.35/0.30, graph 0.51/0.51, rrf_vk 0.31/0.32, rrf_vkg 0.35/0.37, shipped_top5 0.36/0.37, ablate_vkg_no_parent_cap 0.55/0.55, ablate_vg 0.43/0.45, ablate_vg_no_parent_cap 0.58/0.59

Questions with any graph seed: 158/168
