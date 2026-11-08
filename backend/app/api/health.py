from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", responses={503: {"description": "Database unavailable"}})
def ready(request: Request, response: Response) -> dict[str, str]:
    engine = request.app.state.database_engine
    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
            return {"status": "ready"}
        except SQLAlchemyError:
            pass

    response.status_code = 503
    return {"status": "unavailable"}
