"""
APScheduler — runs the Quant analysis pipeline every 4 hours,
stores result in DB and cache, then sends Telegram notification.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.models.database import AnalysisHistory, SymbolWatchlist, get_engine
from app.services.cache import report_cache
from app.services.data_fetcher import fetch_all_timeframes
from app.services.quant_engine import run_analysis
from app.services.telegram_notifier import notifier

logger = logging.getLogger(__name__)

_engine = None   # Set during app startup


def _get_engine():
    global _engine
    if _engine is None:
        _engine = get_engine(os.getenv("DATABASE_URL", "sqlite:///./quant_report.db"))
    return _engine


def run_pipeline(symbol_yf: str = "XAUUSD=X", display_name: str = "XAUUSD", offset_days: int = 0) -> dict | None:
    """Full pipeline: fetch → analyze → cache → persist → notify."""
    logger.info("=== Pipeline START: %s ===", display_name)

    # 1. Fetch OHLCV
    try:
        tfs = fetch_all_timeframes(symbol_yf)
    except Exception as exc:
        logger.error("Data fetch failed: %s — pipeline aborted", exc)
        return None

    # If offsetting, slice the dataframes to simulate a past date
    import pandas as pd
    from datetime import timedelta
    if offset_days > 0:
        cutoff = tfs["h4"].index[-1] - timedelta(days=offset_days)
        tfs["h4"] = tfs["h4"][tfs["h4"].index <= cutoff]
        tfs["d"] = tfs["d"][tfs["d"].index <= cutoff]
        tfs["w"] = tfs["w"][tfs["w"].index <= cutoff]
        tfs["m"] = tfs["m"][tfs["m"].index <= cutoff]

    # 2. Run Analysis
    try:
        result = run_analysis(
            df_h4=tfs["h4"], df_d=tfs["d"], df_w=tfs["w"], df_m=tfs["m"],
            symbol=display_name,
        )
    except Exception as exc:
        logger.error("Analysis failed: %s — pipeline aborted", exc)
        return None

    # 3. Update Cache
    report_cache.set(display_name, result)

    # 4. Persist to DB
    try:
        with Session(_get_engine()) as session:
            sym_row = session.exec(
                select(SymbolWatchlist)
                .where(SymbolWatchlist.symbol == symbol_yf)
            ).first()
            sym_id = sym_row.id if sym_row else 1

            ctx  = result.get("context", {})
            conf = result.get("confluence", {})
            meta = result.get("meta", {})

            # Use candle timestamp from analysis, not wall-clock time
            from dateutil.parser import parse as parse_dt
            try:
                candle_ts = parse_dt(str(meta.get("timestamp", "")))
            except Exception:
                candle_ts = datetime.now(timezone.utc).replace(tzinfo=None)

            record = AnalysisHistory(
                symbol_id       = sym_id,
                timestamp       = candle_ts,
                current_price   = meta.get("current_price", 0),
                trend           = result["trend_regime"]["trend"],
                regime          = result["trend_regime"]["regime"],
                td_phase        = result["td_status"]["phase"],
                context_zone    = ctx.get("zone", "N/A"),
                confluence_score = conf.get("total_score", 0),
                signal_strength = conf.get("strength", "N/A"),
                vr              = ctx.get("vr", 0),
                reach_cl        = ctx.get("reach_cl", 0),
            )
            record.set_report(result)
            session.add(record)
            session.commit()
            logger.info("DB persisted: analysis_history id=%d", record.id or -1)
    except Exception as exc:
        logger.error("DB persist failed: %s", exc)

    # 5. Send Telegram
    notifier.send_report(result)

    logger.info("=== Pipeline DONE: %s ===", display_name)
    return result


def build_scheduler() -> BackgroundScheduler:
    """Create and configure the APScheduler instance."""
    sched = BackgroundScheduler(timezone="UTC")

    # Run at the top of every 4H window aligned to midnight UTC
    # Cron: hour=0,4,8,12,16,20 minute=1 (1 min after candle close to let data settle)
    sched.add_job(
        func=lambda: run_pipeline("XAUUSD=X", "XAUUSD"),
        trigger=CronTrigger(hour="0,4,8,12,16,20", minute=1),
        id="quant_pipeline_xauusd",
        name="Quant XAUUSD 4H Pipeline",
        replace_existing=True,
        misfire_grace_time=300,   # [Error Handling] Run if missed within 5 min window
    )

    return sched
