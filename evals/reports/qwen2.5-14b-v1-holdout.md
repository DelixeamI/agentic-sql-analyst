# Eval report: qwen2.5-14b-v1-holdout

- LLM: `openai:qwen2.5:14b`; dataset v1; 2026-11-12T17:32:19+00:00 → 2026-11-12T17:35:24+00:00
- Hardware: RTX 5070 12GB, Ollama 0.40.8, Q4_K_M

| Metric | Value |
|---|---|
| Execution accuracy (answerable, n=17) | **94.1%** |
| First-try accuracy (no repair) | 94.1% |
| Recovered by self-repair loop | 0 |
| Executable SQL rate | 100.0% |
| Wrong result / failed after retries / false refusals | 1 / 0 / 0 |
| Correct refusals (unanswerable, n=2) | 2/2 |
| Adversarial: database unchanged (n=1) | 1/1 |
| Latency p50 / p95 / mean | 9.3 s / 12.5 s / 9.0 s |
| LLM calls per question | 2.8 |
| Tokens per question (prompt / completion) | 4185 / 462 |
| Cost | $0.0 total, $0.0 per 1000 questions |

## Accuracy by category

| Category | n | EX |
|---|---|---|
| complex | 3 | 66.7% |
| join | 4 | 100.0% |
| nulls | 1 | 100.0% |
| ranking | 2 | 100.0% |
| simple | 4 | 100.0% |
| time | 3 | 100.0% |

## Mean latency by agent

| Agent | Mean, s |
|---|---|
| planner | 3.04 |
| sql_generator | 1.76 |
| synthesizer | 4.13 |

## Misses

| id | question | status | retries | reason |
|---|---|---|---|---|
| h15 | Какой средний чек выполненного заказа в каждом канале продаж? Заказы без канала не учитывай. | success | 0 | no predicted column matches gold column(s): avg |
