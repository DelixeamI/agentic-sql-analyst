# Evaluation methodology

The demo mode proves that the pipeline works. This folder measures how well it works with a real LLM.

## Datasets

| File | Items | Purpose |
|---|---|---|
| [questions.json](questions.json) | 42 answerable + 5 unanswerable + 3 adversarial | Dev set. Prompt changes were made by looking at misses on this set. |
| [holdout.json](holdout.json) | 17 answerable + 2 unanswerable + 1 adversarial | Held-out set. Written before any prompt tuning and never used to tune prompts. It measures whether the fixes generalise. |

Answerable categories: `simple`, `join`, `time`, `ranking`, `nulls` (NULL handling, empty results) and `complex` (ratios, CTE, period comparisons).
Every answerable item has hand-written gold SQL. An integration test checks that each gold query passes the AST guard and returns rows on the seeded database.

## Metrics

- **Execution accuracy (EX).** Run the predicted SQL and the gold SQL and compare result sets, not SQL text. Rules are in [scoring.py](../src/agentic_sql_analyst/evals/scoring.py):
  - only values are compared, column names and column order are ignored;
  - extra predicted columns are allowed, every gold column must be matched by a distinct predicted column;
  - row counts must be equal; row order matters only for ranking items (`"ordered": true`);
  - numbers are equal within `max(0.051, 1e-4 × |gold|)`; dates are compared by their date part.
- **First-try accuracy.** Correct with no repair attempt. EX minus first-try accuracy is the contribution of the self-repair loop.
- **Refusals.** Unanswerable questions must end with status `refused`. A refused answerable question counts as a false refusal.
- **Safety.** For adversarial items the runner takes a fingerprint of every table (row count + md5 of all rows) before and after the question. The item passes only if nothing changed. The whole run fails if the fingerprint changes at any point.
- **Latency.** End-to-end time per question (p50, p95, mean) and mean time per agent, measured inside the LLM client.
- **Tokens and cost.** Prompt and completion tokens from the API `usage` field. Cost = tokens × price, passed with `--price-in` / `--price-out` (USD per 1M tokens). Local models cost $0 in API fees.

## How to run

```bash
docker compose up -d --wait db
ollama pull qwen2.5:14b
uv run analyst eval --model qwen2.5:14b --base-url http://localhost:11434/v1
uv run analyst eval --dataset evals/holdout.json --model qwen2.5:14b --base-url http://localhost:11434/v1 --label qwen2.5-14b-holdout
```

Any OpenAI-compatible endpoint works (`--base-url`, `LLM_API_KEY`). Reports are written to [reports/](reports) as JSON (every item, SQL and reason) and Markdown.

Ollama was started with `OLLAMA_CONTEXT_LENGTH=8192`: the default context is shorter than the longest prompts (schema + plan + error history).

## Known limitations

- 59 answerable questions in total is enough to see large effects (42.9% → 83.3%) but not to separate models that differ by a few points: one question is 2.4 pp on the dev set.
- Questions are in Russian over one synthetic schema; the result says nothing about very wide schemas, where schema retrieval would be needed.
- Each configuration was run once with `temperature=0` and `seed=42`. Local inference is close to deterministic but not guaranteed to be bit-exact.
