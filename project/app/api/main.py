from fastapi import FastAPI

from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import init_db


settings = get_settings()
configure_logging()

app = FastAPI(title=settings.app_name)
app.include_router(health_router)
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def root() -> dict[str, str]:
    return {"app": settings.app_name, "status": "ok"}
