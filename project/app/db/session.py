from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    with engine.begin() as connection:
        if "scheduled_publish_at" not in columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN scheduled_publish_at DATETIME"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
