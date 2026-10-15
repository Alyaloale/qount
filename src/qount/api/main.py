"""FastAPI main application for qount."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from qount.api.db import get_ingest_health, get_last_ingest_time, get_paper_lines_count, init_db
from qount.api.ingest import run_ingest
from qount.api.routes.account import router as account_router
from qount.api.routes.assistant import router as assistant_router
from qount.api.routes.market import router as market_router
from qount.api.routes.paper import router as paper_router
from qount.api.routes.research import router as research_router
from qount.api.schemas import HealthResponse, LineSafety


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database on startup
    init_db()
    if get_paper_lines_count() == 0:
        run_ingest()
    yield


app = FastAPI(
    title="qount API",
    description="Simplified Personal Trading Assistant API",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS middleware for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint
@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Service and database health check."""
    last_ingest = get_last_ingest_time()
    lines_count = get_paper_lines_count()
    ingest_status, stale_count, missing_count = get_ingest_health()
    return HealthResponse(
        status="ok",
        db_connected=True,
        last_ingest_at=last_ingest,
        paper_lines_count=lines_count,
        ingest_status=ingest_status,
        stale_line_count=stale_count,
        missing_source_count=missing_count,
        safety=LineSafety(research_only=True, orders_authorized=False),
    )


# API routers
app.include_router(account_router)
app.include_router(assistant_router)
app.include_router(paper_router)
app.include_router(research_router)
app.include_router(market_router)

# Mount frontend static files from web/app at root (and /app)
web_app_dir = os.path.abspath("web/app")
if os.path.exists(web_app_dir) and os.path.isdir(web_app_dir):
    app.mount("/app", StaticFiles(directory=web_app_dir, html=True), name="web_app")
    app.mount("/", StaticFiles(directory=web_app_dir, html=True), name="site_root")
