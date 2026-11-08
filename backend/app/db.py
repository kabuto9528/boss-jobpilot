from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from .config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings) -> Engine:
    url = URL.create(
        "mysql+pymysql",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        query={"charset": "utf8mb4"},
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 2, "read_timeout": 2, "write_timeout": 2},
        hide_parameters=True,
    )
