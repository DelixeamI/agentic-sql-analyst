# Eval report: qwen2.5-14b-v1

- LLM: `openai:qwen2.5:14b`; dataset v1; 2026-11-12T17:21:48+00:00 → 2026-11-12T17:31:37+00:00
- Hardware: RTX 5070 12GB, Ollama 0.40.8, Q4_K_M

| Metric | Value |
|---|---|
| Execution accuracy (answerable, n=42) | **83.3%** |
| First-try accuracy (no repair) | 76.2% |
| Recovered by self-repair loop | 3 |
| Executable SQL rate | 100.0% |
| Wrong result / failed after retries / false refusals | 7 / 0 / 0 |
| Correct refusals (unanswerable, n=5) | 5/5 |
| Adversarial: database unchanged (n=3) | 3/3 |
| Latency p50 / p95 / mean | 10.7 s / 25.6 s / 11.6 s |
| LLM calls per question | 2.84 |
| Tokens per question (prompt / completion) | 4203 / 487 |
| Cost | $0.0 total, $0.0 per 1000 questions |

## Accuracy by category

| Category | n | EX |
|---|---|---|
| complex | 6 | 33.3% |
| join | 10 | 100.0% |
| nulls | 4 | 100.0% |
| ranking | 6 | 83.3% |
| simple | 8 | 87.5% |
| time | 8 | 87.5% |

## Mean latency by agent

| Agent | Mean, s |
|---|---|
| planner | 3.85 |
| sql_generator | 2.35 |
| sql_repair | 0.22 |
| synthesizer | 5.18 |

## Misses

| id | question | status | retries | reason |
|---|---|---|---|---|
| s06 | Какая средняя цена товара в каталоге? | success | 0 | no predicted column matches gold column(s): avg |
| t08 | Выведи выручку за первый и за второй квартал 2026 года двумя отдельными числами. | success | 0 | row count 2 != gold 1 |
| r04 | Какая категория товаров имеет самую высокую валовую маржинальность? | success | 0 | no predicted column matches gold column(s): name |
| c01 | Какой средний чек выполненного заказа? | success | 0 | no predicted column matches gold column(s): avg |
| c02 | Какой процент заказов возвращён (статус returned) в каждом канале продаж? Заказы без канала не учитывай. | success | 0 | no predicted column matches gold column(s): ?column? |
| c03 | Сколько клиентов сделали больше 20 выполненных заказов? | success | 0 | row count 13 != gold 1 |
| c04 | На сколько процентов выручка за январь–октябрь 2026 года выше, чем за январь–октябрь 2025 года? | success | 0 | no predicted column matches gold column(s): ?column? |
