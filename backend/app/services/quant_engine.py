"""
Quant Engine Service — rewritten to match actual quant_td_pivot_v3.py API
Classes used:
  RegimeFilter, PivotEngine, TDSequentialEngine,
  ProbabilityEngine, ConfluxScorer, PositionSizer,
  MarketRegime, TDPhase, SignalStrength, SystemConfig
"""
from __future__ import annotations

import logging
import traceback

import numpy as np
import pandas as pd

# ── Import original framework ─────────────────────────────────────────────────
try:
    from app.lib.quant_td_pivot_v3 import (  # type: ignore
        SystemConfig,
        RegimeFilter,
        PivotEngine,
        TDSequentialEngine,
        ProbabilityEngine,
        ConfluxScorer,
        PositionSizer,
        MarketRegime,
        TDPhase,
        SignalStrength,
    )
    _ENGINE_AVAILABLE = True
except ImportError as e:
    _ENGINE_AVAILABLE = False
    logging.getLogger(__name__).warning("quant_td_pivot_v3 import failed: %s", e)

logger = logging.getLogger(__name__)
CFG = SystemConfig() if _ENGINE_AVAILABLE else None  # type: ignore


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _trend(df: pd.DataFrame) -> str:
    """EMA crossover + structure-based trend detection from last 20 bars."""
    if len(df) < 20:
        return "SIDEWAYS"
    close = df["close"]
    ema_fast = close.ewm(span=10, adjust=False).mean()
    ema_slow = close.ewm(span=20, adjust=False).mean()
    # EMA crossover direction
    ema_bull = ema_fast.iloc[-1] > ema_slow.iloc[-1]
    ema_bear = ema_fast.iloc[-1] < ema_slow.iloc[-1]
    # Structure confirmation: HH/HL or LH/LL using rolling windows
    highs = df["high"].tail(20)
    lows  = df["low"].tail(20)
    recent_high = highs.tail(5).max()
    prior_high  = highs.head(10).max()
    recent_low  = lows.tail(5).min()
    prior_low   = lows.head(10).min()
    hh_hl = recent_high > prior_high and recent_low > prior_low
    lh_ll = recent_high < prior_high and recent_low < prior_low
    if ema_bull and hh_hl:
        return "UP"
    if ema_bear and lh_ll:
        return "DOWN"
    if ema_bull:
        return "UP"
    if ema_bear:
        return "DOWN"
    return "SIDEWAYS"


def _adr(df_d: pd.DataFrame, period: int = 14) -> float:
    return float((df_d["high"].tail(period) - df_d["low"].tail(period)).mean())


def _compute_context(price: float, pv) -> dict:
    if pv is None:
        return {"zone": "N/A", "bias": "—", "focus": "N/A"}
    p, mr1, r1 = pv.P, pv.MR1, pv.R1
    ms1, s1    = pv.MS1, pv.S1
    if price > r1:
        return {"zone": "R1+",    "bias": "↑↑↑ (extended)",    "focus": "MR2/R2"}
    elif price > mr1:
        return {"zone": "MR1–R1", "bias": "↑↑ (bull)",         "focus": "R1/MR2"}
    elif price > p:
        return {"zone": "P–MR1",  "bias": "↑ (neutral-bull)",  "focus": "MR1/R1"}
    elif price > ms1:
        return {"zone": "MS1–P",  "bias": "↓ (neutral-bear)",  "focus": "MS1/S1"}
    elif price > s1:
        return {"zone": "S1–MS1", "bias": "↓↓ (bear)",         "focus": "S1/MS2"}
    else:
        return {"zone": "S1-",    "bias": "↓↓↓ (extended-bear)","focus": "S2/MS3"}


def _compute_prob_hl(upside_bands, downside_bands) -> tuple[float, float]:
    up   = float(np.mean([b.point_estimate for b in upside_bands]))   if upside_bands   else 50.0
    down = float(np.mean([b.point_estimate for b in downside_bands])) if downside_bands else 50.0
    total = up + down
    if total == 0:
        return 50.0, 50.0
    return round(up / total * 100, 1), round(down / total * 100, 1)


def _compute_vr(df_h4: pd.DataFrame, df_d: pd.DataFrame, period: int = 14) -> float:
    try:
        tr = pd.concat([
            df_h4["high"] - df_h4["low"],
            (df_h4["high"] - df_h4["close"].shift()).abs(),
            (df_h4["low"]  - df_h4["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr_h4 = float(tr.rolling(period).mean().iloc[-1])
        adr_d  = float((df_d["high"].tail(period) - df_d["low"].tail(period)).mean())
        return round(atr_h4 / adr_d, 2) if adr_d > 0 else 0.0
    except Exception:
        return 0.0


def _compute_reach_cl(df_h4: pd.DataFrame, df_d: pd.DataFrame, period: int = 14) -> float:
    try:
        close_now  = float(df_h4["close"].iloc[-1])
        daily_open = float(df_d["open"].iloc[-1])
        adr_d      = float((df_d["high"].tail(period) - df_d["low"].tail(period)).mean())
        return round(abs(close_now - daily_open) / adr_d * 100, 1) if adr_d > 0 else 0.0
    except Exception:
        return 0.0


def _compute_step_extension(bands: list) -> list[dict]:
    steps = []
    for i in range(len(bands) - 1):
        a, b = bands[i], bands[i + 1]
        cond = round(b.point_estimate / a.point_estimate * 100, 1) if a.point_estimate > 0 else 0.0
        steps.append({
            "from_label": a.label, "to_label": b.label,
            "from_level": a.level, "to_level": b.level,
            "conditional_prob": cond,
        })
    return steps


# ─── Main Analysis Runner ─────────────────────────────────────────────────────

def run_analysis(
    df_h4: pd.DataFrame,
    df_d:  pd.DataFrame,
    df_w:  pd.DataFrame,
    df_m:  pd.DataFrame,
    symbol: str = "XAUUSD",
    balance: float = 10_000.0,
) -> dict:
    if not _ENGINE_AVAILABLE:
        raise RuntimeError("quant_td_pivot_v3 engine is not available")

    try:
        t0            = df_h4.index[-1]
        current_price = float(df_h4["close"].iloc[-1])

        # 1. Regime — [GAP-3] Use extended classification with volume + duration
        regime_engine  = RegimeFilter(CFG)
        regime_ext     = regime_engine.classify_extended(df_h4)
        regimes        = regime_ext["regimes"]
        current_regime = regimes.iloc[-1]
        regime_duration = int(regime_ext["duration"].iloc[-1])
        vol_ratio       = float(regime_ext["vol_ratio"].iloc[-1])

        # 2. TD Sequential
        td_engine = TDSequentialEngine(CFG)
        df_td     = td_engine.compute(df_h4)
        td_row    = df_td.iloc[-1]

        # 3. Pivots
        pivot_engine = PivotEngine(CFG)
        pv_map       = pivot_engine.compute_all(df_d, df_w, df_m, t0)
        pv_d         = pv_map.get("D")
        clusters     = pivot_engine.find_cluster_zones(pv_map, current_price)

        # 4. Probabilities — [GAP-4] Use adaptive templates when pivot available
        prob_engine = ProbabilityEngine(CFG)
        if pv_d:
            prob_bands = prob_engine.calculate_adaptive(df_h4, pv_d, regimes)
        else:
            bands_template = prob_engine.calculate(df_h4, regimes)
            prob_bands = []

        # 5. Confluence — [GAP-1] Pass regime_duration for interaction scoring
        trend = _trend(df_h4)
        adr   = _adr(df_d)
        scorer     = ConfluxScorer(CFG)
        # H3: Dynamically select nearest pivot level to current price
        if pv_d:
            pivot_levels = [
                pv_d.S3, pv_d.MS3, pv_d.S2, pv_d.MS2, pv_d.S1, pv_d.MS1,
                pv_d.P, pv_d.MR1, pv_d.R1, pv_d.MR2, pv_d.R2, pv_d.MR3, pv_d.R3,
            ]
            focus_lvl = min(pivot_levels, key=lambda lv: abs(lv - current_price))
        else:
            focus_lvl = current_price
        signal_dir = "BUY" if trend == "UP" else "SELL"
        conf       = scorer.score(
            current_price, focus_lvl, td_row, current_regime,
            clusters, signal_dir, trend, regime_duration=regime_duration,
        )
        strength   = scorer.to_strength(conf.total)

        # 6. New metrics
        context  = _compute_context(current_price, pv_d)
        up_bands = sorted([b for b in prob_bands if b.dist_pct > 0], key=lambda b: b.dist_pct)
        dn_bands = sorted([b for b in prob_bands if b.dist_pct < 0], key=lambda b: b.dist_pct, reverse=True)
        prob_h, prob_l = _compute_prob_hl(up_bands, dn_bands)
        vr       = _compute_vr(df_h4, df_d)
        reach_cl = _compute_reach_cl(df_h4, df_d)
        step_ext = _compute_step_extension(up_bands)
        step_bd  = _compute_step_extension(dn_bands)

        # 7. Determine td_phase
        td_phase_val = td_row.get("td_phase", TDPhase.NONE) if hasattr(df_td, 'get') else getattr(td_row, "td_phase", TDPhase.NONE)
        if hasattr(td_phase_val, 'value'):
            td_phase_str = td_phase_val.value
        else:
            td_phase_str = str(td_phase_val)

        result = {
            "meta": {
                "symbol":        symbol,
                "timestamp":     str(t0),
                "current_price": round(current_price, 2),
                "adr_14":        round(adr, 2),
            },
            "trend_regime": {
                "trend":           trend,
                "regime":          current_regime.value if hasattr(current_regime, 'value') else str(current_regime),
                "is_td_favorable": regime_engine.is_td_favorable(current_regime),
                "regime_duration":  regime_duration,
                "vol_ratio":        round(vol_ratio, 2),
            },
            "context": {
                "zone":     context["zone"],
                "bias":     context["bias"],
                "focus":    context["focus"],
                "prob_h":   prob_h,
                "prob_l":   prob_l,
                "vr":       vr,
                "reach_cl": reach_cl,
            },
            "td_status": {
                "phase":             td_phase_str,
                "setup_count":       int(td_row.get("setup_count", 0)),
                "countdown_count":   int(td_row.get("countdown_count", 0)),
                "tdst":              float(td_row.get("tdst_level", 0) or 0),
                "perfect_setup":     bool(td_row.get("setup_perfect", False)),
                "perfect_countdown": bool(td_row.get("countdown_perfect", False)),
            },
            "levels": {
                "pivots": {k: {
                    "P":   round(pv.P,2),
                    "R1":  round(pv.R1,2), "R2": round(pv.R2,2), "R3": round(pv.R3,2),
                    "S1":  round(pv.S1,2), "S2": round(pv.S2,2), "S3": round(pv.S3,2),
                    "MR1": round(pv.MR1,2),"MR2": round(pv.MR2,2),"MR3": round(pv.MR3,2),
                    "MS1": round(pv.MS1,2),"MS2": round(pv.MS2,2),"MS3": round(pv.MS3,2),
                } for k, pv in pv_map.items()},
                "cluster_zones": [
                    {"name": cz.name, "low": round(cz.low,2), "high": round(cz.high,2), "strength": cz.strength}
                    for cz in (clusters or [])[:5]
                ],
            },
            "probabilities": {
                "upside":   [{"level": round(b.level,2), "label": b.label,
                               "point_estimate": b.point_estimate,
                               "ci_low": b.ci_low, "ci_high": b.ci_high,
                               "regime_bucket": b.regime_bucket} for b in up_bands],
                "downside": [{"level": round(b.level,2), "label": b.label,
                               "point_estimate": b.point_estimate,
                               "ci_low": b.ci_low, "ci_high": b.ci_high,
                               "regime_bucket": b.regime_bucket} for b in dn_bands],
                "step_extension": step_ext,
                "step_breakdown":  step_bd,
            },
            "confluence": {
                "total_score": round(conf.total, 1),
                "strength":    strength.value if hasattr(strength, 'value') else str(strength),
                "details": {
                    "pivot_proximity": round(conf.pivot_score, 1),
                    "td":              round(conf.td_score, 1),
                    "regime":          round(conf.regime_score, 1),
                    "cluster_zone":    round(conf.cz_score, 1),
                },
            },
            "position_sizing": None,
        }

        logger.info("Analysis OK: %s @ %.2f | %s | Score=%.1f",
                    symbol, current_price,
                    result["confluence"]["strength"],
                    result["confluence"]["total_score"])
        return result

    except Exception as exc:
        logger.error("Quant engine error: %s\n%s", exc, traceback.format_exc())
        raise
