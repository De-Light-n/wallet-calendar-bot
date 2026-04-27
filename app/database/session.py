"""Database session and engine setup."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

DATABASE_URL = settings.database_url

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency that provides a database session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables defined in the models."""
    from app.database import models  # noqa: F401 – registers models on Base

    Base.metadata.create_all(bind=engine)

    # Lightweight runtime migration for existing deployments without Alembic.
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    new_user_columns = [
        ("google_spreadsheet_id", "VARCHAR(128)"),
        ("email", "VARCHAR(255)"),
        ("picture_url", "TEXT"),
        ("timezone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
    ]
    with engine.begin() as conn:
        for col_name, col_type in new_user_columns:
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
