"""
Data Fetcher Service
Pulls OHLCV data from yfinance and resamples H4 from 1h bars.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# yfinance does NOT have native 4h — we resample 1h → 4h
_INTERVAL_H1 = "1h"
_PERIOD_H4   = "3mo"   # 3 months of 1h bars → enough for H4 + Daily + Weekly + Monthly
_PERIOD_D    = "2y"    # 2 years of daily bars


def _fetch_raw(symbol: str, interval: str, period: str, retries: int = 3) -> pd.DataFrame:
    """Fetch with exponential backoff retry."""
    import time
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                raise ValueError(f"Empty dataframe from yfinance: {symbol} {interval}")
            
            # yfinance returns MultiIndex columns for single ticker e.g. ('Close', 'GC=F')
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]
                
            df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
            return df
        except Exception as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("yfinance attempt %d/%d failed (%s) — retry in %ds", attempt, retries, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"yfinance fetch failed after {retries} retries: {last_exc}")


def _resample_h4(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h OHLCV into H4 bars. Offset 0h aligns to midnight UTC."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    df_h4 = df_1h.resample("4h", offset="0h").agg(agg).dropna()
    return df_h4


def fetch_all_timeframes(symbol: str = "GC=F") -> dict[str, pd.DataFrame]:
    """
    Returns dict with keys: 'h4', 'd', 'w', 'm'
    All DataFrames have lowercase OHLCV columns and DatetimeIndex.
    """
    logger.info("Fetching 1H bars for H4 resample: %s", symbol)
    df_1h = _fetch_raw(symbol, interval=_INTERVAL_H1, period=_PERIOD_H4)
    df_h4 = _resample_h4(df_1h)
    logger.info("H4 bars after resample: %d", len(df_h4))

    logger.info("Fetching Daily bars: %s", symbol)
    df_d = _fetch_raw(symbol, interval="1d", period=_PERIOD_D)

    df_w = df_d.resample("W").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    df_m = df_d.resample("ME").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()

    logger.info("Timeframes ready — H4:%d D:%d W:%d M:%d",
                len(df_h4), len(df_d), len(df_w), len(df_m))

    return {"h4": df_h4, "d": df_d, "w": df_w, "m": df_m}
