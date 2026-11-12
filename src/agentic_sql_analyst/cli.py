"""Command line interface.

analyst ask "Покажи динамику выручки по месяцам за 2026 год"
analyst schema
analyst graph        # Mermaid diagram of the LangGraph state machine
analyst serve        # run the API + web UI
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agentic_sql_analyst.agents.nodes import AgentDeps
from agentic_sql_analyst.config import get_settings
from agentic_sql_analyst.db.executor import ExecutionResult
from agentic_sql_analyst.graph import mermaid_diagram
from agentic_sql_analyst.llm import DemoLLMClient
from agentic_sql_analyst.schemas import QueryResponse
from agentic_sql_analyst.service import build_resources


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
    serve = sub.add_parser("serve", help="run API + web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "ask":
        return asyncio.run(_ask(args.question, args.json))
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
