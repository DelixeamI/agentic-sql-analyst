"""FastAPI endpoints with injected fakes (no DB, no network)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_sql_analyst.api.app import create_app
from agentic_sql_analyst.db.executor import DatabaseUnavailableError, ExecutionResult
from agentic_sql_analyst.llm.base import AgentTask
from agentic_sql_analyst.service import AnalystService, AppResources
from tests.fakes import FAKE_DDL, PLAN, FakeExecutor, ScriptedLLM, as_json, make_deps


class FakeResources(AppResources):
    def __init__(self, service: AnalystService, *, db_ok: bool = True) -> None:
        super().__init__(service=service)
        self.db_ok = db_ok

    async def check_database(self) -> None:
        if not self.db_ok:
            raise ConnectionRefusedError("db is down")


def _llm() -> ScriptedLLM:
    return ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": "SELECT o.status, COUNT(*) AS orders_count FROM orders o"})],
            AgentTask.SYNTHESIZER: ["broken"],
        }
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(FakeResources(AnalystService(make_deps(_llm()))))
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body == {"status": "ok", "database": "ok", "llm_provider": "scripted", "detail": None}


def test_health_degraded_when_db_down() -> None:
    app = create_app(FakeResources(AnalystService(make_deps(_llm())), db_ok=False))
    with TestClient(app) as test_client:
        body = test_client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


def test_query_returns_full_report(client: TestClient) -> None:
    response = client.post("/query", json={"question": "Сколько заказов по статусам?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["row_count"] == 2
    assert "LIMIT 100" in body["sql"]
    assert body["chart_spec"]["data"]["values"]
    assert body["trace"][0]["node"] == "planner"


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "  a "}, {"question": "x" * 1001}])
def test_query_validation(client: TestClient, payload: dict[str, str]) -> None:
    assert client.post("/query", json=payload).status_code == 422


def test_query_returns_503_when_db_unavailable() -> None:
    def down(sql: str) -> ExecutionResult:
        raise DatabaseUnavailableError("connection refused")

    app = create_app(FakeResources(AnalystService(make_deps(_llm(), FakeExecutor(down)))))
    with TestClient(app) as test_client:
        response = test_client.post("/query", json={"question": "Сколько заказов?"})
    assert response.status_code == 503


def test_schema_endpoint(client: TestClient) -> None:
    assert client.get("/schema").json()["ddl"] == FAKE_DDL


def test_examples_and_index(client: TestClient) -> None:
    examples = client.get("/examples").json()
    assert len(examples) >= 5
    assert {"title", "question"} <= set(examples[0])
    index = client.get("/")
    assert index.status_code == 200
    assert "Agentic SQL Analyst" in index.text
