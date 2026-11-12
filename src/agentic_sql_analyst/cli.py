"""Command line interface.

analyst ask "Покажи динамику выручки по месяцам за 2026 год"
analyst schema
analyst graph        # Mermaid diagram of the LangGraph state machine
analyst eval --model qwen2.5:14b --base-url http://localhost:11434/v1
analyst serve        # run the API + web UI
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from agentic_sql_analyst.agents.nodes import AgentDeps
from agentic_sql_analyst.config import Settings, get_settings
from agentic_sql_analyst.db.executor import ExecutionResult, PostgresExecutor
from agentic_sql_analyst.graph import mermaid_diagram
from agentic_sql_analyst.llm import DemoLLMClient
from agentic_sql_analyst.schemas import QueryResponse
from agentic_sql_analyst.service import build_resources

DATASET = Path("evals/questions.json")


def _print_response(response: QueryResponse) -> None:
    status = response.status.value.upper()
    print(f"\n[{status}] retries: {response.retry_count}, {response.elapsed_ms} ms, llm: {response.llm_provider}")
    print("\nTrace:")
    icons = {"ok": "+", "error": "x", "info": "*"}
    for step in response.trace:
        print(f"  {icons[step.status]} {step.node:<14} {step.duration_ms:>8} ms  {step.detail}")
    if response.sql:
        print(f"\nSQL:\n{response.sql}")
    print(f"\nОтвет: {response.summary}")
    for finding in response.key_findings:
        print(f"  - {finding}")
    if response.rows:
        print(f"\nДанные ({response.row_count} строк, первые 10):")
        for row in response.rows[:10]:
            print("  " + json.dumps(row, ensure_ascii=False))


async def _ask(question: str, as_json: bool) -> int:
    resources = build_resources(get_settings())
    try:
        response = await resources.service.ask(question)
    finally:
        await resources.aclose()
    if as_json:
        print(response.model_dump_json(indent=2))
    else:
        _print_response(response)
    return 0


async def _schema() -> int:
    resources = build_resources(get_settings())
    try:
        print(await resources.service.schema_provider.get_ddl())
    finally:
        await resources.aclose()
    return 0


async def _eval(args: argparse.Namespace) -> int:
    from agentic_sql_analyst.evals.runner import ItemResult, load_dataset, render_markdown, run_eval

    base = get_settings()
    settings = base.model_copy(
        update={
            "llm_provider": args.provider,
            "llm_model": args.model or base.llm_model,
            "llm_base_url": args.base_url or base.llm_base_url,
            "llm_timeout_s": args.timeout,
            "llm_json_mode": not args.no_json_mode,
        }
    )
    Settings.model_validate(settings.model_dump())
    version, items = load_dataset(Path(args.dataset))
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [item for item in items if item.id in wanted]
    resources = build_resources(settings)
    if resources.engine is None:
        raise RuntimeError("evaluation needs a database engine")
    gold_executor = PostgresExecutor(resources.engine, statement_timeout_ms=30_000, max_rows=10_000)
    label = args.label or (settings.llm_model if args.provider == "openai" else "demo")

    def progress(index: int, total: int, result: ItemResult) -> None:
        mark = "OK  " if result.correct else "MISS"
        head = f"[{index:>2}/{total}] {mark} {result.id:<4} {result.elapsed_ms / 1000:6.1f}s"
        print(f"{head} retries={result.retry_count} {result.reason[:90]}")

    try:
        report = await run_eval(
            resources.service,
            resources.engine,
            gold_executor,
            items,
            label=label,
            dataset_version=version,
            hardware=args.hardware,
            price_in=args.price_in,
            price_out=args.price_out,
            on_result=progress,
        )
    finally:
        await resources.aclose()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9.]+", "-", label).strip("-")
    (out_dir / f"{slug}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / f"{slug}.md").write_text(render_markdown(report), encoding="utf-8")
    summary = report.summary["answerable"]
    ex, first = summary["execution_accuracy"], summary["first_try_accuracy"]
    print(f"\nEX={ex:.1%}  first-try={first:.1%}  -> {out_dir / slug}.md")
    return 0


class _NoDb:
    async def execute(self, sql: str) -> ExecutionResult:
        return ExecutionResult()

    async def get_ddl(self) -> str:
        return ""


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="analyst", description="Agentic Text-to-SQL analyst")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="ask a question")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="print raw JSON response")
    sub.add_parser("schema", help="print the DDL the agents see")
    sub.add_parser("graph", help="print the Mermaid diagram of the agent graph")
    ev = sub.add_parser("eval", help="run the gold-set evaluation (execution accuracy, latency, tokens)")
    ev.add_argument("--provider", choices=["openai", "demo"], default="openai")
    ev.add_argument("--model", help="model name, e.g. qwen2.5:14b or gpt-4o-mini")
    ev.add_argument("--base-url", help="OpenAI-compatible endpoint, e.g. http://localhost:11434/v1")
    ev.add_argument("--dataset", default=str(DATASET))
    ev.add_argument("--ids", help="comma-separated subset of item ids")
    ev.add_argument("--label", help="report name (default: model name)")
    ev.add_argument("--out-dir", default="evals/reports")
    ev.add_argument("--hardware", help="free-text hardware note for the report")
    ev.add_argument("--timeout", type=float, default=180.0, help="LLM request timeout, s")
    ev.add_argument("--no-json-mode", action="store_true", help="disable response_format=json_object")
    ev.add_argument("--price-in", type=float, default=0.0, help="USD per 1M input tokens")
    ev.add_argument("--price-out", type=float, default=0.0, help="USD per 1M output tokens")
    serve = sub.add_parser("serve", help="run API + web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "ask":
        return asyncio.run(_ask(args.question, args.json))
    if args.command == "eval":
        return asyncio.run(_eval(args))
    if args.command == "schema":
        return asyncio.run(_schema())
    if args.command == "graph":
        stub = _NoDb()
        print(mermaid_diagram(AgentDeps(llm=DemoLLMClient(), executor=stub, schema_provider=stub)))
        return 0
    import uvicorn

    uvicorn.run("agentic_sql_analyst.api.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
