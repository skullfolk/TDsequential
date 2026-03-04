"""
FastAPI Application — main entrypoint
Routes:
  GET  /api/symbols
  GET  /api/analyze/latest?symbol=XAUUSD
  GET  /api/history/{symbol}
  GET  /api/profile
  PUT  /api/profile
  POST /api/analyze/refresh  (manual trigger)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select

load_dotenv()

from app.models.database import (
    AnalysisHistory,
    SymbolWatchlist,
    UserProfileSettings,
    create_tables,
    get_engine,
    seed_defaults,
)
from app.services.cache import report_cache
from app.services.scheduler import build_scheduler, run_pipeline

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] %(levelname)-8s  %(name)-30s  %(message)s",
)
logger = logging.getLogger(__name__)

_DB_URL  = os.getenv("DATABASE_URL", "sqlite:///./quant_report.db")
_engine  = get_engine(_DB_URL)
_scheduler = build_scheduler()


# ─── App Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables(_engine)
    seed_defaults(_engine)
    _scheduler.start()
    logger.info("APScheduler started — jobs: %s", [j.id for j in _scheduler.get_jobs()])
    yield
    # Shutdown
    _scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")


app = FastAPI(
    title="Quant TD+Pivot Report API",
    version="1.0.0",
    description="Production-grade Quant analysis API for XAUUSD using TD Sequential + Multi-TF Pivot",
    lifespan=lifespan,
)

_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    default_balance: Optional[float] = None
    max_risk_pct: Optional[float]    = None
    max_leverage: Optional[float]    = None
    pip_value_per_lot: Optional[float] = None
    min_lots: Optional[float]        = None
    max_lots_hard_cap: Optional[float] = None


class RefreshRequest(BaseModel):
    symbol_yf: str = "GC=F"
    display_name: str = "XAUUSD"
    offset_days: int = 0


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/symbols", tags=["Symbols"])
def list_symbols():
    """Return all watchlist symbols from DB."""
    with Session(_engine) as session:
        rows = session.exec(select(SymbolWatchlist).where(SymbolWatchlist.is_active == True)).all()
    return {"status": "success", "data": [
        {"id": r.id, "symbol": r.display_name, "ticker": r.symbol, "asset_class": r.asset_class}
        for r in rows
    ]}


@app.get("/api/analyze/latest", tags=["Analysis"])
def get_latest_analysis(symbol: str = "XAUUSD"):
    """
    Returns the last cached analysis result (updated every 4H by APScheduler).
    If cache is stale or empty, returns the last DB record.
    """
    cached = report_cache.get(symbol)
    if cached:
        return {"status": "success", "source": "cache", "data": cached}

    # Fallback to DB
    with Session(_engine) as session:
        sym_row = session.exec(
            select(SymbolWatchlist).where(SymbolWatchlist.display_name == symbol)
        ).first()
        if not sym_row:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        record = session.exec(
            select(AnalysisHistory)
            .where(AnalysisHistory.symbol_id == sym_row.id)
            .order_by(AnalysisHistory.timestamp.desc())  # type: ignore
        ).first()

        if not record:
            raise HTTPException(status_code=404, detail="No analysis data available yet — wait for the next 4H cycle")

        return {"status": "success", "source": "db_fallback", "data": record.get_report()}


@app.get("/api/history/{symbol}", tags=["Analysis"])
def get_history(symbol: str, limit: int = 48):
    """Return last N analysis records for mini-chart display (default 48 = 8 days)."""
    with Session(_engine) as session:
        sym_row = session.exec(
            select(SymbolWatchlist).where(SymbolWatchlist.display_name == symbol)
        ).first()
        if not sym_row:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        records = session.exec(
            select(AnalysisHistory)
            .where(AnalysisHistory.symbol_id == sym_row.id)
            .order_by(AnalysisHistory.timestamp.desc())  # type: ignore
            .limit(limit)
        ).all()

    return {"status": "success", "data": [
        {
            "timestamp": r.timestamp.isoformat(),
            "current_price": r.current_price,
            "trend": r.trend,
            "regime": r.regime,
            "context_zone": r.context_zone,
            "td_phase": r.td_phase,
            "confluence_score": r.confluence_score,
            "signal_strength": r.signal_strength,
            "vr": r.vr,
            "reach_cl": r.reach_cl,
        }
        for r in records
    ]}


@app.get("/api/profile", tags=["Profile"])
def get_profile():
    """Return current user profile settings."""
    with Session(_engine) as session:
        profile = session.get(UserProfileSettings, 1)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "success", "data": profile.model_dump()}


@app.put("/api/profile", tags=["Profile"])
def update_profile(body: ProfileUpdate):
    """Update user profile settings (partial update supported)."""
    with Session(_engine) as session:
        profile = session.get(UserProfileSettings, 1)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(profile, field, value)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return {"status": "success", "data": profile.model_dump()}


@app.post("/api/analyze/refresh", tags=["Analysis"])
def trigger_refresh(body: RefreshRequest, background_tasks: BackgroundTasks):
    """
    Manually trigger a pipeline run (runs in background).
    Returns immediately — check /api/analyze/latest for result.
    """
    report_cache.invalidate(body.display_name)
    background_tasks.add_task(run_pipeline, body.symbol_yf, body.display_name)
    return {"status": "accepted", "message": f"Pipeline queued for {body.display_name}"}


if os.getenv("DEBUG_MODE", "0") == "1":
    @app.post("/api/analyze/debug", tags=["Analysis"])
    def trigger_refresh_sync(body: RefreshRequest):
        """
        DEBUG ONLY: Run the pipeline SYNCHRONOUSLY and return full result or error.
        Only available when DEBUG_MODE=1 is set in environment.
        """
        import traceback as tb
        try:
            result = run_pipeline(body.symbol_yf, body.display_name, offset_days=body.offset_days)
            if result is None:
                raise HTTPException(status_code=500, detail="Pipeline returned None — check server logs")
            return {"status": "success", "data": result}
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}\n\n{tb.format_exc()}"
            raise HTTPException(status_code=500, detail=detail)

