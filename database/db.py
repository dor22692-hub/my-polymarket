from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config import settings
from .models import Base

# Use check_same_thread=False only for SQLite (harmless for Postgres)
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables (idempotent) and apply lightweight column migrations."""
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Add columns introduced in Phase 2 if they don't exist (SQLite compatible)."""
    migrations = [
        ("whale_wallets", "roi", "REAL DEFAULT 0.0"),
    ]
    with engine.connect() as conn:
        for table, col, col_def in migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
                ))
                conn.commit()
            except Exception:
                pass  # column already exists


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
