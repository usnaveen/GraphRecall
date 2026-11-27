# Wired Pipeline Verification (golden.h1.jsonl, n=142)

| arm | recall@1 | recall@5 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| vector | 0.269 | 0.603 [0.53, 0.67] | 0.739 | 0.590 | 0.577 [0.52, 0.64] |
| shipped_top5_old | 0.275 | 0.442 [0.38, 0.50] | 0.697 | 0.577 | 0.432 [0.38, 0.49] |
| wired_fp32_top5 | 0.333 | 0.642 [0.58, 0.71] | 0.817 | 0.662 | 0.590 [0.53, 0.65] |
| wired_int8_top5 | 0.333 | 0.642 [0.58, 0.71] | 0.817 | 0.662 | 0.590 [0.53, 0.65] |

Paired diff vs shipped_top5_old (95% CI):

- vector: recall@1 -0.006, recall@5 +0.161 [+0.102, +0.223], MRR@10 +0.013, nDCG@10 +0.145 [+0.106, +0.189]
- wired_fp32_top5: recall@1 +0.058, recall@5 +0.201 [+0.150, +0.256], MRR@10 +0.085, nDCG@10 +0.158 [+0.111, +0.207]
- wired_int8_top5: recall@1 +0.058, recall@5 +0.201 [+0.150, +0.256], MRR@10 +0.085, nDCG@10 +0.158 [+0.111, +0.207]

Paired diff vs vector (95% CI):

- shipped_top5_old: recall@1 +0.006, recall@5 -0.161 [-0.223, -0.102], nDCG@10 -0.145 [-0.189, -0.106]
- wired_fp32_top5: recall@1 +0.064, recall@5 +0.039 [-0.014, +0.089], nDCG@10 +0.013 [-0.032, +0.056]
- wired_int8_top5: recall@1 +0.064, recall@5 +0.039 [-0.014, +0.089], nDCG@10 +0.013 [-0.032, +0.056]

Latency (ms/query):

- old_e2e_ms: mean=29.49 ms, p50=27.36 ms, p95=36.95 ms
- wired_fp32_e2e_ms: mean=206.99 ms, p50=180.96 ms, p95=395.08 ms
- wired_int8_e2e_ms: mean=192.78 ms, p50=167.21 ms, p95=342.09 ms
- ce_fp32_ms: mean=178.72 ms, p50=156.7 ms, p95=336.27 ms
- ce_int8_ms: mean=165.47 ms, p50=142.05 ms, p95=263.16 ms
