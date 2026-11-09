from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes.auth import router as auth_router
from app.api.routes.shipments import router as shipments_router
from app.api.routes.workflow import router as workflow_router
from app.api.routes.reports import router as reports_router
from app.core.config import get_cors_origins, settings
from app.db.session import Base, engine

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(validation_results)")).fetchall()
        }
        if columns and "human_confirmed" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE validation_results "
                    "ADD COLUMN human_confirmed BOOLEAN DEFAULT 0 NOT NULL"
                )
            )


@app.on_event("startup")
def create_tables() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        ensure_sqlite_columns()


app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
app.include_router(shipments_router, prefix="/api/shipments", tags=["shipments"])
app.include_router(workflow_router, prefix="/api/shipments", tags=["document workflow"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
