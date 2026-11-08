from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)


def load_database_settings(*, testing: bool = False) -> DatabaseSettings:
    filename, database, user = (
        (".env.test", "boss_jobs_test", "boss_app_test")
        if testing
        else (".env", "boss_jobs", "boss_app")
    )
    try:
        with (PROJECT_ROOT / filename).open(encoding="utf-8-sig") as config_file:
            values = dotenv_values(stream=config_file, interpolate=False)
        port = int(values.get("DB_PORT") or "")
    except (OSError, ValueError):
        raise DatabaseConfigError(f"Check the database configuration in {filename}.") from None

    host = values.get("DB_HOST")
    password = values.get("DB_PASSWORD")
    if (
        host not in ("127.0.0.1", "localhost")
        or not 1 <= port <= 65535
        or values.get("DB_NAME") != database
        or values.get("DB_USER") != user
        or not password
        or password in ("replace_with_app_password", "replace_with_test_password")
    ):
        raise DatabaseConfigError(f"Check the database configuration in {filename}.")

    return DatabaseSettings(host, port, database, user, password)
