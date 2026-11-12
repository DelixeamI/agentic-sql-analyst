# Eval report: qwen2.5-14b-v0-baseline

- LLM: `openai:qwen2.5:14b`; dataset v1; 2026-11-12T17:06:33+00:00 → 2026-11-12T17:19:17+00:00
- Hardware: RTX 5070 12GB, Ollama 0.40.8, Q4_K_M

| Metric | Value |
|---|---|
| Execution accuracy (answerable, n=42) | **42.9%** |
| First-try accuracy (no repair) | 38.1% |
| Recovered by self-repair loop | 2 |
| Executable SQL rate | 71.4% |
| Wrong result / failed after retries / false refusals | 12 / 12 / 0 |
| Correct refusals (unanswerable, n=5) | 0/5 |
| Adversarial: database unchanged (n=3) | 3/3 |
| Latency p50 / p95 / mean | 10.6 s / 57.6 s / 15.2 s |
| LLM calls per question | 2.38 |
| Tokens per question (prompt / completion) | 3323 / 436 |
| Cost | $0.0 total, $0.0 per 1000 questions |

## Accuracy by category

| Category | n | EX |
|---|---|---|
| complex | 6 | 16.7% |
| join | 10 | 90.0% |
| nulls | 4 | 25.0% |
| ranking | 6 | 33.3% |
| simple | 8 | 12.5% |
| time | 8 | 50.0% |

## Mean latency by agent

| Agent | Mean, s |
|---|---|
| planner | 6.06 |
| sql_generator | 2.63 |
| sql_repair | 0.84 |
| synthesizer | 5.60 |

## Misses

| id | question | status | retries | reason |
|---|---|---|---|---|
| s02 | Сколько заказов было отменено (статус cancelled)? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s03 | Сколько товаров в каталоге неактивны? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s04 | Сколько клиентов в каждом сегменте? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s05 | Сколько заказов приходится на каждый статус? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s06 | Какая средняя цена товара в каталоге? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s07 | Сколько клиентов не указали город? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| s08 | Какой самый дорогой товар в каталоге и сколько он стоит? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| j09 | Какая выручка по городам клиентов? Клиентов без города не учитывай. | success | 0 | no predicted column matches gold column(s): sum |
| t01 | Сколько заказов (в любом статусе) было оформлено в каждом месяце 2025 года? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| t03 | Какая выручка была в каждом квартале 2025 года? | success | 0 | row count 1 != gold 4 |
| t05 | Сколько клиентов зарегистрировалось в 2024 году? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| t07 | Какая суммарная выручка за ноябрь и декабрь 2025 года? | success | 0 | row count 2 != gold 1 |
| r02 | Какие 3 города дают наибольшую выручку? | success | 0 | no predicted column matches gold column(s): revenue |
| r03 | Какие 5 клиентов потратили больше всего денег? Выведи имя и сумму. | success | 0 | no predicted column matches gold column(s): full_name, spent |
| r04 | Какая категория товаров имеет самую высокую валовую маржинальность? | success | 0 | no predicted column matches gold column(s): name |
| r06 | Назови 3 категории с наименьшим количеством проданных единиц товара в выполненных заказах и это количество. | success | 0 | no predicted column matches gold column(s): name, units |
| n01 | Сколько выполненных заказов не имеют указанного канала продаж? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| n02 | Какой процент от всех заказов не имеет указанного канала продаж? | failed | 0 | status=failed: Не удалось построить план запроса: LLM answer violates PlannerOutput contract: 1 error(s) |
| n04 | Сколько клиентов ни разу не сделали ни одного заказа? | success | 0 | row count 0 != gold 1 |
| c02 | Какой процент заказов возвращён (статус returned) в каждом канале продаж? Заказы без канала не учитывай. | success | 0 | no predicted column matches gold column(s): ?column? |
| c03 | Сколько клиентов сделали больше 20 выполненных заказов? | success | 0 | row count 100 != gold 1 |
| c04 | На сколько процентов выручка за январь–октябрь 2026 года выше, чем за январь–октябрь 2025 года? | failed | 3 | status=failed: Безопасный отказ: запрос не удалось исправить после 3 попыток исправления. Последняя ошибка: GroupingError [42803]: column "subquery.total_revenue_2025" must ap |
| c05 | Каковы топ-3 категории товаров с наибольшим падением выручки во 2 квартале 2026 года по сравнению с первым? Покажи процент изменения. | success | 0 | no predicted column matches gold column(s): name, change_pct |
| c06 | Какой процент всей выручки приходится на три самые прибыльные по выручке категории вместе? | success | 0 | row count 3 != gold 1 |
| u01 | Какая погода была в Москве в день самого крупного заказа? | failed | 0 | expected refusal, got status=failed |
| u02 | Сколько посетителей было на сайте в октябре 2026 года? | failed | 0 | expected refusal, got status=failed |
| u03 | Какой средний рейтинг отзывов у ноутбуков? | failed | 0 | expected refusal, got status=failed |
| u04 | Какая маржинальность у каждого поставщика? | failed | 0 | expected refusal, got status=failed |
| u05 | Сколько стоила доставка заказов в Казань? | failed | 0 | expected refusal, got status=failed |
