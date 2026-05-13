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
    added_columns = [
        ("scheduled_publish_at", "DATETIME"),
        ("source_id", "VARCHAR(100)"),
        ("is_auto_crawled", "BOOLEAN DEFAULT 0"),
        ("crawl_mood", "VARCHAR(30)"),
        ("preview_video_path", "TEXT"),
        ("preview_thumbnail_path", "TEXT"),
        ("youtube_title", "TEXT"),
        ("youtube_description", "TEXT"),
        ("youtube_tags", "TEXT"),
        ("music_track_path", "TEXT"),
        ("youtube_video_id", "VARCHAR(50)"),
        ("youtube_url", "TEXT"),
        ("review_expires_at", "DATETIME"),
    ]
    with engine.begin() as connection:
        for name, ddl in added_columns:
            if name not in columns:
                connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
