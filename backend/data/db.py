from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import PROJECT_ROOT, get_settings
from .models import Base


def _build_engine():
    settings = get_settings()
    database_url = settings.database_url
    if database_url.startswith("sqlite:///./"):
        relative_path = database_url.removeprefix("sqlite:///./")
        database_url = f"sqlite:///{(PROJECT_ROOT / relative_path).resolve()}"
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


ENGINE = _build_engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)


def _ensure_sqlite_columns() -> None:
    if ENGINE.dialect.name != "sqlite":
        return

    inspector = inspect(ENGINE)
    if "profiles" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("profiles")}
    required_columns = {
        "health_status": "ALTER TABLE profiles ADD COLUMN health_status VARCHAR(32) NOT NULL DEFAULT 'unknown'",
        "health_reason": "ALTER TABLE profiles ADD COLUMN health_reason TEXT",
        "last_checked_at": "ALTER TABLE profiles ADD COLUMN last_checked_at DATETIME",
    }

    with ENGINE.begin() as connection:
        for column_name, statement in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(statement))


def initialize_database() -> None:
    Base.metadata.create_all(bind=ENGINE)
    _ensure_sqlite_columns()


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
