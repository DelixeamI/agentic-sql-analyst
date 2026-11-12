"""FastAPI application: `/query`, `/health`, `/schema`, `/examples` and the demo UI at `/`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from agentic_sql_analyst import __version__
from agentic_sql_analyst.config import get_settings
from agentic_sql_analyst.db.executor import DatabaseUnavailableError
from agentic_sql_analyst.llm.demo_client import SCENARIOS
from agentic_sql_analyst.schemas import (
    ExampleQuestion,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
)
from agentic_sql_analyst.service import AnalystService, AppResources, build_resources

logger = logging.getLogger("agentic_sql_analyst")

STATIC_DIR = Path(__file__).parent / "static"


def get_resources(request: Request) -> AppResources:
    return request.app.state.resources  # type: ignore[no-any-return]


def get_service(resources: Annotated[AppResources, Depends(get_resources)]) -> AnalystService:
    return resources.service


def create_app(resources: AppResources | None = None) -> FastAPI:
    """Application factory. Pass `resources` to inject fakes in tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = resources is None
        app.state.resources = resources or build_resources(get_settings())
        logger.info("LLM provider: %s", app.state.resources.service.llm_name)
        try:
            yield
        finally:
            if owned:
                await app.state.resources.aclose()

    app = FastAPI(
        title="agentic-sql-analyst",
        version=__version__,
        description="Autonomous multi-agent Text-to-SQL analyst with a zero-trust SQL sandbox.",
        lifespan=lifespan,
    )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health(resources: Annotated[AppResources, Depends(get_resources)]) -> HealthResponse:
        try:
            await resources.check_database()
        except Exception as error:  # noqa: BLE001 - health must never raise
            return HealthResponse(
                status="degraded",
                database="unavailable",
                llm_provider=resources.service.llm_name,
                detail=f"{type(error).__name__}: {error}"[:300],
            )
        return HealthResponse(status="ok", database="ok", llm_provider=resources.service.llm_name)

    @app.get("/schema", response_model=SchemaResponse, tags=["analyst"])
    async def schema(service: Annotated[AnalystService, Depends(get_service)]) -> SchemaResponse:
        try:
            ddl = await service.schema_provider.get_ddl()
        except (DatabaseUnavailableError, OSError) as error:
            raise HTTPException(status_code=503, detail=f"database unavailable: {error}") from error
        return SchemaResponse(ddl=ddl)

    @app.get("/examples", response_model=list[ExampleQuestion], tags=["analyst"])
    async def examples() -> list[ExampleQuestion]:
        return [ExampleQuestion(title=s.title, question=s.question) for s in SCENARIOS]

    @app.post("/query", response_model=QueryResponse, tags=["analyst"])
    async def query(
        payload: QueryRequest,
        service: Annotated[AnalystService, Depends(get_service)],
    ) -> QueryResponse:
        try:
            return await service.ask(payload.question)
        except (DatabaseUnavailableError, OSError) as error:
            raise HTTPException(status_code=503, detail=f"database unavailable: {error}") from error

    return app


app = create_app()
