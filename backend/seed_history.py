from __future__ import annotations

import logging
from datetime import timedelta
import pandas as pd
from sqlmodel import Session, select
import sys
import os

from app.models.database import AnalysisHistory, SymbolWatchlist, get_engine
from app.services.data_fetcher import fetch_all_timeframes
from app.services.quant_engine import run_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_history")

# Update this path if needed
DB_URL = "sqlite:///quant_report.db"
engine = get_engine(DB_URL)

def seed_history(symbol_yf: str = "GC=F", display_name: str = "XAUUSD", lookback_bars: int = 100):
    """
    Fetches the current data, then simulates running the pipeline for each of the last N bars.
    """
    logger.info("Fetching data for %s", symbol_yf)
    tfs = fetch_all_timeframes(symbol_yf)
    
    df_h4 = tfs["h4"]
    df_d = tfs["d"]
    df_w = tfs["w"]
    df_m = tfs["m"]
    
    if len(df_h4) < lookback_bars + 20: # Need enough data to slice
        logger.warning("Not enough data to look back %d bars. DataFrame has %d rows.", lookback_bars, len(df_h4))
        lookback_bars = max(1, len(df_h4) - 20)

    logger.info("Seeding DB with the last %d bars", lookback_bars)
    
    with Session(engine) as session:
        # Get symbol
        sym_row = session.exec(
            select(SymbolWatchlist).where(SymbolWatchlist.symbol == symbol_yf)
        ).first()
        sym_id = sym_row.id if sym_row else 1

        # Clear existing history to replace it with continuous backfill
        session.exec(select(AnalysisHistory).where(AnalysisHistory.symbol_id == sym_id))
        existing_records = session.exec(select(AnalysisHistory).where(AnalysisHistory.symbol_id == sym_id)).all()
        for record in existing_records:
            session.delete(record)
        session.commit()
        logger.info("Cleared existing history for %s", display_name)

        # Loop from past to present
        new_records = []
        for i in range(lookback_bars, -1, -1):
            if i == 0:
                h4_slice = df_h4
                d_slice = df_d
                w_slice = df_w
                m_slice = df_m
            else:
                cutoff = df_h4.index[-1] - timedelta(hours=4*i)
                h4_slice = df_h4[df_h4.index <= cutoff]
                if len(h4_slice) == 0:
                    continue
                actual_cutoff = h4_slice.index[-1]
                d_slice = df_d[df_d.index <= actual_cutoff]
                w_slice = df_w[df_w.index <= actual_cutoff]
                m_slice = df_m[df_m.index <= actual_cutoff]

            if len(h4_slice) < 50:
                continue # Needs minimum bars for TD and Pivot

            try:
                result = run_analysis(
                    df_h4=h4_slice, df_d=d_slice, df_w=w_slice, df_m=m_slice,
                    symbol=display_name,
                )
                
                ctx  = result.get("context", {})
                conf = result.get("confluence", {})
                meta = result.get("meta", {})
                
                record = AnalysisHistory(
                    symbol_id       = sym_id,
                    timestamp       = h4_slice.index[-1].to_pydatetime().replace(tzinfo=None),
                    current_price   = meta.get("current_price", 0),
                    trend           = result["trend_regime"]["trend"],
                    regime          = result["trend_regime"]["regime"],
                    td_phase        = result["td_status"]["phase"],
                    context_zone    = ctx.get("zone", "N/A"),
                    confluence_score = conf.get("total_score", 0),
                    signal_strength = conf.get("strength", "WEAK"),
                    vr              = ctx.get("vr", 0),
                    reach_cl        = ctx.get("reach_cl", 0),
                )
                record.set_report(result)
                session.add(record)
                new_records.append(record)
            except Exception as e:
                logger.error("Failed bar %d: %s", i, e)

        session.commit()
        logger.info("Successfully seeded %d historical records ending at %s", len(new_records), new_records[-1].timestamp if new_records else "None")

if __name__ == "__main__":
    seed_history(lookback_bars=60)
