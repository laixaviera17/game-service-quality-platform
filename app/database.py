from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, Engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "game_quality.db"
metadata = MetaData()

players = Table(
    "players",
    metadata,
    Column("player_id", String(64), primary_key=True),
    Column("nickname", String(128), nullable=False),
    Column("gem_balance", Integer, nullable=False, server_default="0"),
    Column("account_status", String(16), nullable=False, server_default="active"),
    CheckConstraint("gem_balance >= 0", name="ck_player_non_negative_balance"),
)
activities = Table(
    "activities",
    metadata,
    Column("activity_id", String(64), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("reward_gems", Integer, nullable=False),
    Column("stock", Integer, nullable=False),
    Column("initial_stock", Integer, nullable=False),
    Column("per_player_limit", Integer, nullable=False, server_default="1"),
    Column("status", String(16), nullable=False),
    CheckConstraint("reward_gems > 0", name="ck_activity_positive_reward"),
    CheckConstraint("stock >= 0", name="ck_activity_non_negative_stock"),
    CheckConstraint("initial_stock >= 0", name="ck_activity_non_negative_initial_stock"),
    CheckConstraint("per_player_limit > 0", name="ck_activity_positive_player_limit"),
)
reward_grants = Table(
    "reward_grants",
    metadata,
    Column("grant_id", Integer, primary_key=True, autoincrement=True),
    Column("player_id", String(64), ForeignKey("players.player_id"), nullable=False),
    Column("activity_id", String(64), ForeignKey("activities.activity_id"), nullable=False),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("reward_gems", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
quality_runs = Table(
    "quality_runs",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("trigger", String(32), nullable=False),
    Column("started_at", String(40), nullable=False),
    Column("completed_at", String(40), nullable=False),
    Column("status", String(16), nullable=False),
    Column("rules", Integer, nullable=False),
    Column("failed_rules", Integer, nullable=False),
    Column("total_findings", Integer, nullable=False),
)
quality_run_findings = Table(
    "quality_run_findings",
    metadata,
    Column("run_id", Integer, ForeignKey("quality_runs.run_id"), primary_key=True),
    Column("rule", String(64), primary_key=True),
    Column("title", String(128), nullable=False),
    Column("description", String(255), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("finding_count", Integer, nullable=False),
    Column("passed", Integer, nullable=False),
    Column("samples_json", Text, nullable=False),
)
test_runs = Table(
    "test_runs",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("trigger", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", String(40), nullable=False),
    Column("completed_at", String(40)),
    Column("total_cases", Integer, nullable=False, server_default="0"),
    Column("passed_cases", Integer, nullable=False, server_default="0"),
    Column("failed_cases", Integer, nullable=False, server_default="0"),
    Column("error_message", Text),
)
test_run_configs = Table(
    "test_run_configs",
    metadata,
    Column("run_id", Integer, ForeignKey("test_runs.run_id"), primary_key=True),
    Column("scenario_codes_json", Text, nullable=False),
    Column("options_json", Text, nullable=False),
)
test_case_results = Table(
    "test_case_results",
    metadata,
    Column("result_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("test_runs.run_id"), nullable=False),
    Column("case_code", String(64), nullable=False),
    Column("title", String(128), nullable=False),
    Column("status", String(16), nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("request_json", Text, nullable=False),
    Column("response_json", Text, nullable=False),
    Column("assertion_json", Text, nullable=False),
    Column("error_message", Text),
)

_engine: Engine | None = None
_engine_url: str | None = None


def database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    path = Path(os.getenv("GAME_QA_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path}"


def get_engine() -> Engine:
    global _engine, _engine_url
    url = database_url()
    if _engine is not None and _engine_url == url:
        return _engine
    if _engine is not None:
        _engine.dispose()
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()
    _engine = engine
    _engine_url = url
    return engine


@contextmanager
def connect() -> Iterator[Connection]:
    connection = get_engine().connect()
    try:
        yield connection
        if connection.in_transaction():
            connection.commit()
    except BaseException:
        if connection.in_transaction():
            connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    engine = get_engine()
    metadata.create_all(engine)
    with connect() as connection:
        _migrate_existing_sqlite_schema(connection)


def _migrate_existing_sqlite_schema(connection: Connection) -> None:
    """Keep local SQLite demo databases created by older project versions usable."""
    if connection.dialect.name != "sqlite":
        return
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "players" in tables:
        player_columns = {column["name"] for column in inspector.get_columns("players")}
        if "account_status" not in player_columns:
            connection.execute(text("ALTER TABLE players ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active'"))
    if "activities" in tables:
        activity_columns = {column["name"] for column in inspector.get_columns("activities")}
        if "initial_stock" not in activity_columns:
            connection.execute(text("ALTER TABLE activities ADD COLUMN initial_stock INTEGER"))
        if "per_player_limit" not in activity_columns:
            connection.execute(text("ALTER TABLE activities ADD COLUMN per_player_limit INTEGER NOT NULL DEFAULT 1"))
        connection.execute(text("UPDATE activities SET initial_stock = stock WHERE initial_stock IS NULL"))
