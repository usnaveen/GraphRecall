# Wired Pipeline Verification (golden.r4.jsonl, n=171)

| arm | recall@1 | recall@5 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| vector | 0.170 | 0.448 [0.38, 0.51] | 0.608 | 0.445 | 0.443 [0.38, 0.50] |
| shipped_top5_old | 0.173 | 0.360 [0.31, 0.42] | 0.596 | 0.432 | 0.330 [0.28, 0.38] |
| wired_fp32_top5 | 0.242 | 0.499 [0.44, 0.56] | 0.690 | 0.536 | 0.462 [0.40, 0.52] |
| wired_int8_top5 | 0.248 | 0.503 [0.44, 0.56] | 0.690 | 0.539 | 0.464 [0.41, 0.52] |

Paired diff vs shipped_top5_old (95% CI):

- vector: recall@1 -0.004, recall@5 +0.088 [+0.040, +0.139], MRR@10 +0.013, nDCG@10 +0.113 [+0.080, +0.149]
- wired_fp32_top5: recall@1 +0.069, recall@5 +0.139 [+0.092, +0.188], MRR@10 +0.104, nDCG@10 +0.131 [+0.086, +0.178]
- wired_int8_top5: recall@1 +0.075, recall@5 +0.143 [+0.094, +0.194], MRR@10 +0.107, nDCG@10 +0.134 [+0.088, +0.181]

Paired diff vs vector (95% CI):

- shipped_top5_old: recall@1 +0.004, recall@5 -0.088 [-0.139, -0.040], nDCG@10 -0.113 [-0.149, -0.080]
- wired_fp32_top5: recall@1 +0.072, recall@5 +0.051 [+0.004, +0.095], nDCG@10 +0.018 [-0.024, +0.058]
- wired_int8_top5: recall@1 +0.078, recall@5 +0.055 [+0.006, +0.101], nDCG@10 +0.021 [-0.020, +0.061]

Latency (ms/query):

- old_e2e_ms: mean=28.8 ms, p50=28.66 ms, p95=37.31 ms
- wired_fp32_e2e_ms: mean=364.06 ms, p50=336.74 ms, p95=541.02 ms
- wired_int8_e2e_ms: mean=191.04 ms, p50=176.43 ms, p95=293.62 ms
- ce_fp32_ms: mean=338.02 ms, p50=311.69 ms, p95=517.66 ms
- ce_int8_ms: mean=164.08 ms, p50=152.3 ms, p95=253.61 ms
