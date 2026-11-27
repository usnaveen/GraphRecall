# Wired Pipeline Verification (golden.h1.jsonl, n=142)

| arm | recall@1 | recall@5 | hit@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| vector | 0.269 | 0.603 [0.53, 0.67] | 0.739 | 0.590 | 0.577 [0.52, 0.64] |
| shipped_top5_old | 0.275 | 0.442 [0.38, 0.50] | 0.697 | 0.577 | 0.432 [0.38, 0.49] |
| wired_fp32_top5 | 0.337 | 0.628 [0.56, 0.69] | 0.803 | 0.673 | 0.590 [0.53, 0.65] |
| wired_int8_top5 | 0.333 | 0.638 [0.57, 0.70] | 0.810 | 0.668 | 0.591 [0.53, 0.65] |

Paired diff vs shipped_top5_old (95% CI):

- vector: recall@1 -0.006, recall@5 +0.161 [+0.102, +0.223], MRR@10 +0.013, nDCG@10 +0.145 [+0.106, +0.189]
- wired_fp32_top5: recall@1 +0.061, recall@5 +0.186 [+0.132, +0.243], MRR@10 +0.095, nDCG@10 +0.158 [+0.111, +0.207]
- wired_int8_top5: recall@1 +0.058, recall@5 +0.196 [+0.142, +0.254], MRR@10 +0.091, nDCG@10 +0.159 [+0.110, +0.209]

Paired diff vs vector (95% CI):

- shipped_top5_old: recall@1 +0.006, recall@5 -0.161 [-0.223, -0.102], nDCG@10 -0.145 [-0.189, -0.106]
- wired_fp32_top5: recall@1 +0.068, recall@5 +0.025 [-0.026, +0.074], nDCG@10 +0.013 [-0.029, +0.053]
- wired_int8_top5: recall@1 +0.064, recall@5 +0.035 [-0.015, +0.084], nDCG@10 +0.013 [-0.028, +0.054]

Latency (ms/query):

- old_e2e_ms: mean=30.94 ms, p50=27.19 ms, p95=47.58 ms
- wired_fp32_e2e_ms: mean=390.47 ms, p50=372.31 ms, p95=543.09 ms
- wired_int8_e2e_ms: mean=205.61 ms, p50=196.83 ms, p95=295.87 ms
- ce_fp32_ms: mean=365.3 ms, p50=349.91 ms, p95=499.15 ms
- ce_int8_ms: mean=180.27 ms, p50=173.2 ms, p95=261.45 ms
