from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.applications import router as applications_router
from .api.dashboard import router as dashboard_router
from .api.health import router
from .api.jobs import router as jobs_router
from .api.tasks import router as tasks_router
from .api.settings import router as settings_router
from .config import DatabaseConfigError, DatabaseSettings, load_database_settings
from .db import create_database_engine
from .runner.task_runner import TaskRunner


logger = logging.getLogger(__name__)


def create_app(
    database_settings: DatabaseSettings | None = None,
    *,
    control_origins: frozenset[str] | None = None,
    fixture_submit_cases: dict[int, str] | None = None,
) -> FastAPI:
    if fixture_submit_cases is not None and (
        database_settings is None
        or database_settings.host not in {"127.0.0.1", "localhost"}
        or (database_settings.database, database_settings.user) != ("boss_jobs_test", "boss_app_test")
    ):
        raise ValueError("Fixture submission requires the isolated local test database and account.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        try:
            settings = database_settings or load_database_settings()
            engine = create_database_engine(settings)
        except DatabaseConfigError as exc:
            logger.warning("%s", exc)

        app.state.database_engine = engine
        runner = TaskRunner(engine, fixture_submit_cases=fixture_submit_cases) if engine is not None else None
        app.state.task_runner = runner
        try:
            if runner is not None:
                runner.start()
            yield
        finally:
            if runner is not None:
                runner.stop()
            if engine is not None:
                engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.fixture_simulation_enabled = fixture_submit_cases is not None
    app.state.control_origins = control_origins if control_origins is not None else frozenset(
        f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (5173, 8000)
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.warning("Database request failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": {"code": "DATABASE_UNAVAILABLE", "message": "数据库暂不可用"}})

    app.include_router(router)
    app.include_router(jobs_router)
    app.include_router(tasks_router)
    app.include_router(applications_router)
    app.include_router(dashboard_router)
    app.include_router(settings_router)
    return app


app = create_app()
