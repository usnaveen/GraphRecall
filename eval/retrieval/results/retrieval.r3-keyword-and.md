# Retrieval eval (golden.r3.jsonl, n=168)

| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| vector | 0.229 | 0.494 [0.43, 0.56] | 0.634 | 0.685 | 0.514 | 0.503 [0.45, 0.56] |
| keyword | 0.053 | 0.063 [0.03, 0.10] | 0.069 | 0.083 | 0.074 | 0.067 [0.03, 0.10] |
| graph | 0.208 | 0.423 [0.36, 0.49] | 0.506 | 0.554 | 0.417 | 0.412 [0.35, 0.47] |
| rrf_vk | 0.238 | 0.343 [0.29, 0.40] | 0.366 | 0.583 | 0.480 | 0.357 [0.30, 0.41] |
| rrf_vkg | 0.245 | 0.343 [0.29, 0.40] | 0.363 | 0.589 | 0.480 | 0.358 [0.30, 0.41] |
| shipped_top5 | 0.238 | 0.343 [0.29, 0.40] | 0.343 | 0.589 | 0.468 | 0.341 [0.29, 0.40] |

Difference vs vector (paired, 95% CI):

- keyword: recall@5 -0.431 [-0.497, -0.370], nDCG@10 -0.437 [-0.494, -0.382]
- graph: recall@5 -0.071 [-0.116, -0.028], nDCG@10 -0.091 [-0.139, -0.050]
- rrf_vk: recall@5 -0.151 [-0.199, -0.103], nDCG@10 -0.146 [-0.182, -0.112]
- rrf_vkg: recall@5 -0.152 [-0.201, -0.103], nDCG@10 -0.146 [-0.181, -0.108]
- shipped_top5: recall@5 -0.151 [-0.200, -0.102], nDCG@10 -0.162 [-0.196, -0.128]

By question type (recall@5 / nDCG@10):

- Complex Reasoning (n=57): vector 0.45/0.45, keyword 0.01/0.01, graph 0.37/0.38, rrf_vk 0.29/0.29, rrf_vkg 0.29/0.29, shipped_top5 0.28/0.27
- Contextual Summarize (n=51): vector 0.49/0.47, keyword 0.00/0.00, graph 0.38/0.34, rrf_vk 0.28/0.30, rrf_vkg 0.28/0.30, shipped_top5 0.29/0.28
- Fact Retrieval (n=60): vector 0.54/0.58, keyword 0.17/0.18, graph 0.51/0.51, rrf_vk 0.45/0.47, rrf_vkg 0.45/0.47, shipped_top5 0.45/0.46

Questions with any graph seed: 158/168
