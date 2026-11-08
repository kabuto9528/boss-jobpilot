from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.health import router
from .api.jobs import router as jobs_router
from .api.tasks import router as tasks_router
from .config import DatabaseConfigError, DatabaseSettings, load_database_settings
from .db import create_database_engine
from .runner.task_runner import TaskRunner


logger = logging.getLogger(__name__)


def create_app(database_settings: DatabaseSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        try:
            settings = database_settings or load_database_settings()
            engine = create_database_engine(settings)
        except DatabaseConfigError as exc:
            logger.warning("%s", exc)

        app.state.database_engine = engine
        runner = TaskRunner(engine) if engine is not None else None
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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.include_router(router)
    app.include_router(jobs_router)
    app.include_router(tasks_router)
    return app


app = create_app()
