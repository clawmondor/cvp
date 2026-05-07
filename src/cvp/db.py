"""SQLAlchemy 2.x database session and engine configuration."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cvp.config import settings


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:") or url.startswith("sqlite+")


def _coerce_pg_url(url: str) -> str:
    """Railway and other providers supply postgresql:// or postgres://.
    SQLAlchemy uses psycopg2 for those schemes by default; we ship psycopg3
    (psycopg[binary]), so rewrite the scheme to use the psycopg3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _ensure_data_dirs() -> None:
    """Create required data directories at module import time."""
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.export_dir).mkdir(parents=True, exist_ok=True)
    db_file = settings.database_url.replace("sqlite:///", "")
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)


_db_url = _coerce_pg_url(settings.database_url)
_is_sqlite = _is_sqlite_url(_db_url)

if _is_sqlite:
    _ensure_data_dirs()
    engine = create_engine(
        _db_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_wal_mode(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        """Enable WAL journal mode for SQLite."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

else:
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
