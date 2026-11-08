from fastapi import HTTPException, Request
from sqlalchemy.engine import Engine


def database_engine(request: Request) -> Engine:
    engine = request.app.state.database_engine
    if engine is None:
        raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    return engine


def require_local_control(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.control_origins:
        raise HTTPException(403, detail={"code": "ORIGIN_DENIED", "message": "此来源不能修改本地管理记录"})
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    # Keep the existing bodyless stop contract for local CLI clients.
    cli_stop = origin is None and request.url.path.endswith("/stop") and not media_type
    if media_type != "application/json" and not cli_stop:
        raise HTTPException(415, detail={"code": "JSON_REQUIRED", "message": "请使用 JSON 请求"})
