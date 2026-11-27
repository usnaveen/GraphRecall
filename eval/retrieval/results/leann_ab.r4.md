# LEANN vs Current Retrieval A/B Eval (golden.r4.jsonl, n=171)

| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| vector | 0.170 | 0.448 [0.38, 0.51] | 0.579 | 0.608 | 0.445 | 0.443 [0.38, 0.50] |
| shipped_top5 | 0.173 | 0.360 [0.31, 0.42] | 0.360 | 0.596 | 0.432 | 0.330 [0.28, 0.38] |
| ablate_vkg_no_cap | 0.198 | 0.448 [0.38, 0.51] | 0.596 | 0.637 | 0.470 | 0.464 [0.40, 0.52] |
| graph_1hop | 0.177 | 0.379 [0.31, 0.45] | 0.479 | 0.503 | 0.397 | 0.386 [0.32, 0.45] |
| graph_naive_2hop | 0.174 | 0.434 [0.37, 0.50] | 0.538 | 0.579 | 0.434 | 0.426 [0.37, 0.49] |
| graph_hub_pruned_2hop | 0.174 | 0.441 [0.38, 0.51] | 0.549 | 0.585 | 0.435 | 0.433 [0.37, 0.49] |
| leann_two_level_ce | 0.242 | 0.511 [0.45, 0.57] | 0.634 | 0.696 | 0.546 | 0.517 [0.46, 0.57] |
| leann_two_level_ce_rrf | 0.213 | 0.472 [0.41, 0.54] | 0.618 | 0.661 | 0.493 | 0.486 [0.43, 0.54] |
| leann_two_level_full | 0.211 | 0.477 [0.42, 0.54] | 0.575 | 0.678 | 0.508 | 0.470 [0.42, 0.53] |
| binary_only | 0.170 | 0.453 [0.39, 0.52] | 0.552 | 0.614 | 0.446 | 0.429 [0.37, 0.49] |
| leann_binary_to_cosine | 0.170 | 0.445 [0.38, 0.51] | 0.578 | 0.608 | 0.446 | 0.443 [0.38, 0.50] |
| leann_binary_to_ce | 0.242 | 0.517 [0.45, 0.58] | 0.644 | 0.708 | 0.549 | 0.522 [0.47, 0.58] |

Paired diff vs shipped_top5 (95% CI):

- vector: recall@1 -0.004 [-0.024, +0.016], recall@5 +0.088 [+0.040, +0.139], MRR@10 +0.013, nDCG@10 +0.113 [+0.080, +0.149]
- ablate_vkg_no_cap: recall@1 +0.025 [-0.009, +0.060], recall@5 +0.088 [+0.050, +0.127], MRR@10 +0.037, nDCG@10 +0.134 [+0.102, +0.166]
- graph_1hop: recall@1 +0.004 [-0.028, +0.037], recall@5 +0.019 [-0.038, +0.074], MRR@10 -0.035, nDCG@10 +0.056 [+0.008, +0.103]
- graph_naive_2hop: recall@1 +0.000 [-0.022, +0.025], recall@5 +0.074 [+0.024, +0.125], MRR@10 +0.001, nDCG@10 +0.096 [+0.061, +0.136]
- graph_hub_pruned_2hop: recall@1 +0.000 [-0.022, +0.025], recall@5 +0.081 [+0.032, +0.131], MRR@10 +0.002, nDCG@10 +0.102 [+0.069, +0.142]
- leann_two_level_ce: recall@1 +0.069 [+0.019, +0.117], recall@5 +0.152 [+0.104, +0.200], MRR@10 +0.114, nDCG@10 +0.186 [+0.141, +0.232]
- leann_two_level_ce_rrf: recall@1 +0.039 [+0.001, +0.081], recall@5 +0.112 [+0.067, +0.156], MRR@10 +0.061, nDCG@10 +0.156 [+0.119, +0.192]
- leann_two_level_full: recall@1 +0.038 [-0.000, +0.076], recall@5 +0.117 [+0.071, +0.165], MRR@10 +0.076, nDCG@10 +0.140 [+0.106, +0.175]
- binary_only: recall@1 -0.003 [-0.042, +0.037], recall@5 +0.093 [+0.039, +0.149], MRR@10 +0.013, nDCG@10 +0.098 [+0.056, +0.141]
- leann_binary_to_cosine: recall@1 -0.004 [-0.024, +0.016], recall@5 +0.085 [+0.037, +0.136], MRR@10 +0.014, nDCG@10 +0.112 [+0.079, +0.149]
- leann_binary_to_ce: recall@1 +0.069 [+0.019, +0.118], recall@5 +0.157 [+0.109, +0.207], MRR@10 +0.117, nDCG@10 +0.192 [+0.147, +0.238]

Paired diff vs vector (95% CI):

- shipped_top5: recall@1 +0.004, recall@5 -0.088 [-0.139, -0.040], nDCG@10 -0.113 [-0.149, -0.080]
- ablate_vkg_no_cap: recall@1 +0.028, recall@5 +0.000 [-0.045, +0.044], nDCG@10 +0.021 [-0.011, +0.051]
- graph_1hop: recall@1 +0.007, recall@5 -0.069 [-0.107, -0.031], nDCG@10 -0.057 [-0.094, -0.021]
- graph_naive_2hop: recall@1 +0.004, recall@5 -0.014 [-0.035, +0.005], nDCG@10 -0.017 [-0.038, +0.002]
- graph_hub_pruned_2hop: recall@1 +0.004, recall@5 -0.007 [-0.028, +0.012], nDCG@10 -0.011 [-0.031, +0.008]
- leann_two_level_ce: recall@1 +0.072, recall@5 +0.064 [+0.015, +0.109], nDCG@10 +0.073 [+0.033, +0.113]
- leann_two_level_ce_rrf: recall@1 +0.043, recall@5 +0.024 [-0.023, +0.069], nDCG@10 +0.043 [+0.007, +0.076]
- leann_two_level_full: recall@1 +0.041, recall@5 +0.029 [-0.015, +0.071], nDCG@10 +0.027 [-0.008, +0.061]
- binary_only: recall@1 +0.000, recall@5 +0.005 [-0.038, +0.047], nDCG@10 -0.015 [-0.044, +0.014]
- leann_binary_to_cosine: recall@1 +0.000, recall@5 -0.003 [-0.009, +0.000], nDCG@10 -0.001 [-0.007, +0.004]
- leann_binary_to_ce: recall@1 +0.072, recall@5 +0.069 [+0.020, +0.118], nDCG@10 +0.079 [+0.038, +0.119]

By question type (recall@5 / nDCG@10):

- Complex Reasoning (n=57): vector 0.35/0.39, shipped_top5 0.34/0.31, ablate_vkg_no_cap 0.44/0.47, graph_1hop 0.33/0.38, graph_naive_2hop 0.37/0.40, graph_hub_pruned_2hop 0.37/0.40, leann_two_level_ce 0.48/0.48, leann_two_level_ce_rrf 0.44/0.45, leann_two_level_full 0.47/0.42, binary_only 0.37/0.40, leann_binary_to_cosine 0.35/0.40, leann_binary_to_ce 0.49/0.47
- Contextual Summarize (n=54): vector 0.40/0.38, shipped_top5 0.28/0.25, ablate_vkg_no_cap 0.37/0.38, graph_1hop 0.34/0.35, graph_naive_2hop 0.38/0.37, graph_hub_pruned_2hop 0.40/0.39, leann_two_level_ce 0.46/0.46, leann_two_level_ce_rrf 0.40/0.43, leann_two_level_full 0.40/0.41, binary_only 0.35/0.35, leann_binary_to_cosine 0.40/0.38, leann_binary_to_ce 0.45/0.47
- Fact Retrieval (n=60): vector 0.58/0.55, shipped_top5 0.46/0.42, ablate_vkg_no_cap 0.52/0.54, graph_1hop 0.47/0.43, graph_naive_2hop 0.55/0.50, graph_hub_pruned_2hop 0.55/0.50, leann_two_level_ce 0.59/0.60, leann_two_level_ce_rrf 0.56/0.56, leann_two_level_full 0.56/0.57, binary_only 0.62/0.53, leann_binary_to_cosine 0.57/0.55, leann_binary_to_ce 0.60/0.62

Latency (ms/query):

- binary_ce_batch40_ms: mean=568.38 ms, p50=540.11 ms, p95=786.94 ms
- binary_hamming_596_ms: mean=0.62 ms, p50=0.45 ms, p95=0.66 ms
- ce_batch30_ms: mean=423.78 ms, p50=403.11 ms, p95=623.51 ms
- graph_1hop_ms: mean=14.01 ms, p50=12.26 ms, p95=22.47 ms
- graph_hub_pruned_2hop_ms: mean=26.7 ms, p50=17.6 ms, p95=32.47 ms
- graph_naive_2hop_ms: mean=27.27 ms, p50=15.7 ms, p95=29.79 ms
- leann_full_rerank_ms: mean=407.01 ms, p50=389.05 ms, p95=550.51 ms
- shipped_end_to_end_ms: mean=32.78 ms, p50=32.25 ms, p95=43.92 ms
- vec_kw_ms: mean=24.31 ms, p50=22.17 ms, p95=37.93 ms

Binary quantization storage (n=596 child chunks, 768 dims): float32=1788.0 KB vs 1-bit packed=55.9 KB (32.0x smaller).
