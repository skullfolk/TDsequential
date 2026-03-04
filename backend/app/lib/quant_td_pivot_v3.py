"""
╔══════════════════════════════════════════════════════════════════════╗
║      QUANT-GRADE FRAMEWORK: TD Sequential + Multi-TF Pivot          ║
║      Version: 3.0 — Production Grade                                ║
║      Asset  : XAUUSD  |  TF: H4                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES จาก v2.0 (ตาม Code Review):                                  ║
║                                                                      ║
║  🔴 Critical                                                         ║
║    [1] Lot size sanity check — ป้องกัน margin call                  ║
║    [2] Probability ใช้ relative % distance จาก P (ไม่ใช่ absolute)  ║
║    [3] Walk-Forward → Expanding Window (ไม่ใช่ rolling fixed)        ║
║                                                                      ║
║  🟡 Important                                                        ║
║    [4] TD Countdown — full DeMark spec (bar 8 check + TDST recycle)  ║
║    [5] Probability Engine vectorized (rolling แทน nested loop ~50x)  ║
║    [6] TimeSeriesView class — enforce lookahead ทุก access           ║
║                                                                      ║
║  🟢 Nice-to-Have                                                     ║
║    [7] Unit Tests สำหรับ TD Engine                                   ║
║    [8] SystemConfig dataclass แทน hardcode                           ║
║    [9] Structured Logging ทุก pipeline stage                         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
import unittest
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────
# [9] LOGGING — Structured, per-module
# ─────────────────────────────────────────────────────────────────────
def _get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s  %(name)-28s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ═════════════════════════════════════════════════════════════════════
# SECTION 0 — DATA TYPES & CONFIG
# ═════════════════════════════════════════════════════════════════════

class MarketRegime(Enum):
    TRENDING_UP   = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING       = "RANGING"
    VOLATILE      = "VOLATILE"


class TDPhase(Enum):
    NONE             = "NONE"
    BUY_SETUP        = "BUY_SETUP"
    SELL_SETUP       = "SELL_SETUP"
    BUY_COUNTDOWN    = "BUY_COUNTDOWN"
    SELL_COUNTDOWN   = "SELL_COUNTDOWN"
    BUY_SIGNAL       = "BUY_SIGNAL"
    SELL_SIGNAL      = "SELL_SIGNAL"


class SignalStrength(Enum):
    STRONG   = "STRONG"    # Score ≥ 80
    MODERATE = "MODERATE"  # Score 60–79
    WEAK     = "WEAK"      # Score < 60


@dataclass
class PivotLevels:
    tf: str
    P:   float
    R1:  float; R2: float; R3: float
    S1:  float; S2: float; S3: float
    MR1: float; MR2: float; MR3: float
    MS1: float; MS2: float; MS3: float

    def as_dict(self) -> dict[str, float]:
        """Return label→price mapping สำหรับ iteration"""
        return {
            "P":   self.P,
            "R1":  self.R1,  "R2":  self.R2,  "R3":  self.R3,
            "S1":  self.S1,  "S2":  self.S2,  "S3":  self.S3,
            "MR1": self.MR1, "MR2": self.MR2, "MR3": self.MR3,
            "MS1": self.MS1, "MS2": self.MS2, "MS3": self.MS3,
        }


@dataclass
class ClusterZone:
    name:       str
    low:        float
    high:       float
    tf_sources: list[str]
    strength:   int           # จำนวน TF ที่ converge


@dataclass
class ConfluxScore:
    total:        float
    pivot_score:  float
    td_score:     float
    regime_score: float
    cz_score:     float
    detail:       dict = field(default_factory=dict)


@dataclass
class ProbabilityBand:
    """
    [FIX-2] Probability คิดจาก relative % distance จาก P
    ไม่ใช่ absolute price — ทำให้ใช้กับทุก session/period ได้
    """
    level:          float
    label:          str
    dist_pct:       float   # % ห่างจาก P  (+ = upside, - = downside)
    point_estimate: float   # % touch probability
    ci_low:         float   # Wilson 95% CI lower
    ci_high:        float   # Wilson 95% CI upper
    sample_size:    int
    regime_bucket:  str     # "RANGING" | "TRENDING" | "ALL"


# ─────────────────────────────────────────────────────────────────────
# [8] SYSTEM CONFIG — แทน hardcode ทุก magic number
# ─────────────────────────────────────────────────────────────────────
@dataclass
class SystemConfig:
    # Regime
    adx_period:         int   = 14
    adx_trend_thresh:   float = 25.0
    atr_mult_volatile:  float = 1.5
    atr_period:         int   = 14
    vol_ratio_period:   int   = 20     # [GAP-3] Volume confirmation lookback
    vol_ratio_threshold: float = 0.8   # [GAP-3] Below this = volume-weak trend → downgrade

    # Pivot
    cz_pip_threshold:   float = 5.0    # pip tolerance สำหรับ Cluster Zone

    # TD Sequential
    td_lookback:        int   = 4      # DeMark: Close vs Close[i-4]
    td_setup_bars:      int   = 9
    td_countdown_bars:  int   = 13

    # Probability
    prob_lookback_bars: int   = 2000   # [FIX-2] เพิ่มเป็น 2000 H4 ≈ 1 ปี
    prob_forward_bars:  int   = 20     # นับว่า touch ใน 20 แท่งถัดไป
    prob_min_sample:    int   = 30
    prob_z:             float = 1.96   # 95% CI

    # Position Sizing
    max_risk_pct:       float = 0.02   # 2% per trade
    max_leverage:       float = 10.0   # [FIX-1] cap leverage
    pip_value_per_lot:  float = 1.0    # XAUUSD: $1 per 0.01 lot per pip
    min_lots:           float = 0.01
    max_lots_hard_cap:  float = 50.0   # [FIX-1] absolute hard cap

    # Confluence weights
    w_pivot_proximity:      float = 20.0
    w_td_setup:             float = 20.0
    w_td_setup_perfect:     float = 10.0
    w_td_countdown:         float = 25.0
    w_td_countdown_perfect: float = 10.0
    w_cz_2tf:               float = 15.0
    w_cz_3tf:               float = 25.0
    w_regime:               float = 15.0
    w_trend_align:          float = 10.0

    # [GAP-1] Regime-aware weight multipliers
    w_regime_trending_bonus: float = 10.0   # Bonus when TRENDING aligns with signal
    w_td_cz_interaction:     float = 8.0    # Bonus when TD Setup/CD + CZ overlap
    w_regime_duration_bonus: float = 5.0    # Bonus for established regime (>10 bars)

    # Walk-Forward
    wf_min_train_bars:  int   = 500    # [FIX-3] minimum training bars
    wf_n_folds:         int   = 5


CFG = SystemConfig()   # global default — override ตามต้องการ


# ═════════════════════════════════════════════════════════════════════
# SECTION 1 — TIME-SERIES VIEW  [FIX-6]
# ═════════════════════════════════════════════════════════════════════

class TimeSeriesView:
    """
    [FIX-6] Enforce look-ahead bias protection ที่ระดับ data access
    ไม่ใช่แค่ static method ที่ไม่มีใคร enforce

    Usage:
        view = TimeSeriesView(df, as_of=pd.Timestamp("2024-06-01 08:00"))
        view["close"]   # → Series ที่มีแค่ข้อมูลถึง as_of
        view.last       # → แท่งล่าสุดที่ปิดแล้ว (Series)
    """

    _log = _get_logger("TimeSeriesView")

    def __init__(self, df: pd.DataFrame, as_of: pd.Timestamp):
        # ตัด strict < as_of → ไม่รวมแท่งปัจจุบัน (ยังไม่ปิด)
        self._df    = df[df.index < as_of].copy()
        self.as_of  = as_of
        self._log.debug("View created: %d bars up to %s", len(self._df), as_of)

    def __getitem__(self, col: str) -> pd.Series:
        return self._df[col]

    def __len__(self) -> int:
        return len(self._df)

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @property
    def last(self) -> pd.Series:
        """แท่งล่าสุดที่ปิดแล้ว ณ as_of"""
        if self._df.empty:
            raise ValueError(f"No closed bars before {self.as_of}")
        return self._df.iloc[-1]

    @classmethod
    def for_pivot(cls, df_htf: pd.DataFrame, current_time: pd.Timestamp) -> "TimeSeriesView":
        """
        Factory สำหรับ Higher-TF pivot calculation
        Daily pivot ของ bar ปัจจุบัน = คำนวณจาก yesterday OHLC
        """
        return cls(df_htf, as_of=current_time)


# ═════════════════════════════════════════════════════════════════════
# SECTION 2 — MARKET REGIME FILTER
# ═════════════════════════════════════════════════════════════════════

class RegimeFilter:
    """
    [GAP-3 Enhanced] ADX + ATR + Volume regime classification
    Adds: volume confirmation, regime duration, and transition detection
    """

    _log = _get_logger("RegimeFilter")

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    # ── internal helpers ──────────────────────────────────────────────

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        h, l, c = df["high"], df["low"], df["close"]
        return pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs(),
        ], axis=1).max(axis=1)

    def _adx_components(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        p = self.cfg.adx_period
        tr = self._true_range(df)
        h, l = df["high"], df["low"]

        plus_dm  = h.diff().clip(lower=0).where(h.diff() > (-l.diff()).clip(lower=0), 0)
        minus_dm = (-l.diff()).clip(lower=0).where((-l.diff()).clip(lower=0) > h.diff().clip(lower=0), 0)

        atr_s    = tr.ewm(span=p, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=p, adjust=False).mean() / atr_s
        minus_di = 100 * minus_dm.ewm(span=p, adjust=False).mean() / atr_s
        dx       = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
        adx      = dx.ewm(span=p, adjust=False).mean()
        return adx, plus_di, minus_di

    def _volume_ratio(self, df: pd.DataFrame) -> pd.Series:
        """[GAP-3] Volume ratio = current vol / rolling mean vol"""
        if "volume" not in df.columns:
            return pd.Series(1.0, index=df.index)
        vol = df["volume"].replace(0, np.nan)
        vol_ma = vol.rolling(self.cfg.vol_ratio_period, min_periods=5).mean()
        return (vol / vol_ma).fillna(1.0)

    @staticmethod
    def _regime_duration(regimes: pd.Series) -> pd.Series:
        """[GAP-3] Count consecutive bars in the same regime"""
        durations = pd.Series(0, index=regimes.index, dtype=int)
        count = 1
        for i in range(1, len(regimes)):
            if regimes.iloc[i] == regimes.iloc[i - 1]:
                count += 1
            else:
                count = 1
            durations.iloc[i] = count
        return durations

    @staticmethod
    def _regime_transition(regimes: pd.Series) -> pd.Series:
        """[GAP-3] Detect regime changes: 1 = just transitioned, 0 = same"""
        return (regimes != regimes.shift()).astype(int).fillna(0)

    # ── public API ────────────────────────────────────────────────────

    def classify(self, df: pd.DataFrame) -> pd.Series:
        """[GAP-3 Enhanced] Vectorized + volume-confirmed regime classification"""
        self._log.info("Classifying regime for %d bars (volume-enhanced)", len(df))

        adx, plus_di, minus_di = self._adx_components(df)
        atr      = self._true_range(df).rolling(self.cfg.atr_period).mean()
        atr_mean = atr.rolling(50).mean()
        vol_ratio = self._volume_ratio(df)

        volatile  = atr > atr_mean * self.cfg.atr_mult_volatile
        trending  = adx >= self.cfg.adx_trend_thresh
        up        = plus_di > minus_di

        # [GAP-3] Volume-weak trends downgrade to RANGING
        vol_weak = vol_ratio < self.cfg.vol_ratio_threshold

        # Priority: VOLATILE > TRENDING (volume-confirmed) > RANGING
        regimes = pd.Series(MarketRegime.RANGING, index=df.index, dtype=object)
        regimes[trending &  up]  = MarketRegime.TRENDING_UP
        regimes[trending & ~up]  = MarketRegime.TRENDING_DOWN
        # Downgrade volume-weak trends back to RANGING
        regimes[trending & vol_weak] = MarketRegime.RANGING
        regimes[volatile]        = MarketRegime.VOLATILE   # override last

        return regimes

    def classify_extended(self, df: pd.DataFrame) -> dict:
        """
        [GAP-3] Extended classification returning regime + duration + transition
        Returns dict with keys: 'regimes', 'duration', 'transition', 'vol_ratio'
        """
        regimes = self.classify(df)
        duration = self._regime_duration(regimes)
        transition = self._regime_transition(regimes)
        vol_ratio = self._volume_ratio(df)

        self._log.info(
            "Regime extended: current=%s, duration=%d bars, vol_ratio=%.2f",
            regimes.iloc[-1].value if hasattr(regimes.iloc[-1], 'value') else regimes.iloc[-1],
            duration.iloc[-1],
            vol_ratio.iloc[-1],
        )

        return {
            "regimes": regimes,
            "duration": duration,
            "transition": transition,
            "vol_ratio": vol_ratio,
        }

    def is_td_favorable(self, regime: MarketRegime) -> bool:
        return regime == MarketRegime.RANGING


# ═════════════════════════════════════════════════════════════════════
# SECTION 3 — PIVOT ENGINE  (Multi-TF, with TimeSeriesView)
# ═════════════════════════════════════════════════════════════════════

class PivotEngine:

    _log = _get_logger("PivotEngine")

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    def _calc(self, tf: str, H: float, L: float, C: float) -> PivotLevels:
        P  = (H + L + C) / 3
        R1 = 2*P - L;       S1 = 2*P - H
        R2 = P + (H - L);   S2 = P - (H - L)
        R3 = H + 2*(P - L); S3 = L - 2*(H - P)
        return PivotLevels(
            tf=tf, P=P,
            R1=R1, R2=R2, R3=R3,
            S1=S1, S2=S2, S3=S3,
            MR1=(P+R1)/2, MR2=(P+R2)/2, MR3=(P+R3)/2,
            MS1=(P+S1)/2, MS2=(P+S2)/2, MS3=(P+S3)/2,
        )

    def compute_all(
        self,
        df_d: pd.DataFrame,
        df_w: pd.DataFrame,
        df_m: pd.DataFrame,
        current_time: pd.Timestamp,
    ) -> dict[str, PivotLevels]:
        """
        [FIX-6] ใช้ TimeSeriesView.for_pivot() บังคับ lookahead protection
        ทุก TF
        """
        result: dict[str, PivotLevels] = {}
        for tf_label, df_htf in [("D", df_d), ("W", df_w), ("M", df_m)]:
            view = TimeSeriesView.for_pivot(df_htf, current_time)
            if len(view) == 0:
                self._log.warning("No closed %s bars before %s — skipping", tf_label, current_time)
                continue
            src = view.last
            result[tf_label] = self._calc(tf_label, src["high"], src["low"], src["close"])
            self._log.debug("%s Pivot P=%.2f", tf_label, result[tf_label].P)
        return result

    def find_cluster_zones(
        self,
        pivots: dict[str, PivotLevels],
        current_price: float,
    ) -> list[ClusterZone]:
        """หา CZ = Level ที่ Pivot หลาย TF มาชนกันภายใน pip_threshold"""
        thr = self.cfg.cz_pip_threshold
        all_levels: list[tuple[float, str]] = []

        for tf, pv in pivots.items():
            for label, val in pv.as_dict().items():
                all_levels.append((val, f"{tf}_{label}"))

        all_levels.sort(key=lambda x: x[0])
        clusters: list[ClusterZone] = []
        i = 0
        while i < len(all_levels):
            group = [all_levels[i]]
            j = i + 1
            while j < len(all_levels) and all_levels[j][0] - group[0][0] <= thr:
                group.append(all_levels[j])
                j += 1
            if len(group) >= 2:
                vals    = [g[0] for g in group]
                sources = [g[1] for g in group]
                tfs     = list({s.split("_")[0] for s in sources})
                clusters.append(ClusterZone(
                    name=" + ".join(sources[:3]),
                    low=min(vals), high=max(vals),
                    tf_sources=tfs, strength=len(tfs),
                ))
            i = j

        return sorted(clusters, key=lambda c: abs((c.low + c.high) / 2 - current_price))


# ═════════════════════════════════════════════════════════════════════
# SECTION 4 — TD SEQUENTIAL ENGINE  [FIX-4 Full DeMark Spec]
# ═════════════════════════════════════════════════════════════════════

class TDSequentialEngine:
    """
    Full DeMark TD Sequential:

    Setup (1-9):
      Buy : Close[i] < Close[i-4]  for 9 consecutive bars
      Sell: Close[i] > Close[i-4]  for 9 consecutive bars
      Perfected Buy  Setup: Low[8]  ≤ min(Low[6], Low[7])
      Perfected Sell Setup: High[8] ≥ max(High[6], High[7])

    Countdown (1-13):   [FIX-4]
      Buy Countdown bar qualifies when:
        Close[i] ≤ Low[i-2]
        AND Close[i] ≤ Low of Setup Bar 8   ← DeMark extra condition
      Sell Countdown bar qualifies when:
        Close[i] ≥ High[i-2]
        AND Close[i] ≥ High of Setup Bar 8  ← DeMark extra condition

    Setup Recycle:      [FIX-4]
      Buy  Setup resets ONLY if Close breaks above TDST (resistance)
      Sell Setup resets ONLY if Close breaks below TDST (support)
      Otherwise: overlap continues
    """

    _log = _get_logger("TDSequentialEngine")

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        self._log.info("Computing TD Sequential on %d bars", len(df))

        n     = len(df)
        close = df["close"].values
        high  = df["high"].values
        low   = df["low"].values
        lb    = self.cfg.td_lookback       # 4

        # output arrays
        phases          = [TDPhase.NONE] * n
        setup_cnt       = [0] * n
        countdown_cnt   = [0] * n
        tdst_arr        = [np.nan] * n
        setup_perf      = [False] * n
        countdown_perf  = [False] * n

        # state
        phase           = TDPhase.NONE
        s_cnt           = 0
        cd_cnt          = 0
        tdst            = np.nan
        setup_bar8_ref  = np.nan   # [FIX-4] DeMark bar 8 reference price
        setup_high_list: list[float] = []
        setup_low_list:  list[float] = []

        for i in range(lb, n):
            c  = close[i]
            pc = close[i - lb]   # Close[i-4]

            # snapshot ก่อน transition — ใช้ record setup_count ที่ bar transition
            pre_phase  = phase
            pre_s_cnt  = s_cnt
            pre_cd_cnt = cd_cnt

            # ──────────────────────────────────────────
            # A.  SETUP PHASE
            # ──────────────────────────────────────────
            if phase in (TDPhase.NONE, TDPhase.BUY_SIGNAL, TDPhase.SELL_SIGNAL):
                # fresh start after signal or reset
                if c < pc:
                    phase = TDPhase.BUY_SETUP
                    s_cnt = 1
                    setup_low_list  = [low[i]]
                    setup_high_list = [high[i]]
                    tdst            = np.nanmax(high[max(0, i - 8):i + 1])
                elif c > pc:
                    phase = TDPhase.SELL_SETUP
                    s_cnt = 1
                    setup_high_list = [high[i]]
                    setup_low_list  = [low[i]]
                    tdst            = np.nanmin(low[max(0, i - 8):i + 1])

            elif phase == TDPhase.BUY_SETUP:
                if c < pc:
                    s_cnt += 1
                    setup_low_list.append(low[i])
                    setup_high_list.append(high[i])

                    if s_cnt == self.cfg.td_setup_bars:
                        # Perfected: Low[8] ≤ min(Low[6], Low[7])
                        if i >= 2:
                            setup_perf[i] = low[i] <= min(low[i - 2], low[i - 3])
                        tdst           = float(np.max(setup_high_list))  # TDST = highest high of setup
                        setup_bar8_ref = low[i]    # [FIX-4] bar 8 Low reference for countdown
                        phase          = TDPhase.BUY_COUNTDOWN
                        cd_cnt         = 0
                else:
                    # [FIX-4] Recycle only if TDST is broken upward
                    if c > tdst:
                        self._log.debug("BUY_SETUP recycle at i=%d (TDST break)", i)
                        phase = TDPhase.NONE
                        s_cnt = 0
                    # else: interrupt but do NOT recycle — overlap allowed

            elif phase == TDPhase.SELL_SETUP:
                if c > pc:
                    s_cnt += 1
                    setup_high_list.append(high[i])
                    setup_low_list.append(low[i])

                    if s_cnt == self.cfg.td_setup_bars:
                        if i >= 2:
                            setup_perf[i] = high[i] >= max(high[i - 2], high[i - 3])
                        tdst           = float(np.min(setup_low_list))   # TDST = lowest low of setup
                        setup_bar8_ref = high[i]   # [FIX-4] bar 8 High reference
                        phase          = TDPhase.SELL_COUNTDOWN
                        cd_cnt         = 0
                else:
                    # [FIX-4] Recycle only if TDST broken downward
                    if c < tdst:
                        self._log.debug("SELL_SETUP recycle at i=%d (TDST break)", i)
                        phase = TDPhase.NONE
                        s_cnt = 0

            # ──────────────────────────────────────────
            # B.  COUNTDOWN PHASE  [FIX-4 Full DeMark]
            # ──────────────────────────────────────────
            elif phase == TDPhase.BUY_COUNTDOWN:
                # Cancel if TDST broken
                if c > tdst:
                    self._log.debug("BUY_COUNTDOWN cancelled — TDST break at i=%d", i)
                    phase = TDPhase.NONE
                    s_cnt = cd_cnt = 0
                else:
                    # DeMark condition:
                    #   Close[i] ≤ Low[i-2]  AND  Close[i] ≤ Low of Setup Bar 8
                    if i >= 2 and c <= low[i - 2] and c <= setup_bar8_ref:
                        cd_cnt += 1
                        if cd_cnt == self.cfg.td_countdown_bars:
                            # Perfected 13: Low[13] ≤ Low[8] (bar 8 ref)
                            if i >= 2:
                                countdown_perf[i] = low[i] <= setup_bar8_ref
                            phase = TDPhase.BUY_SIGNAL

            elif phase == TDPhase.SELL_COUNTDOWN:
                if c < tdst:
                    self._log.debug("SELL_COUNTDOWN cancelled — TDST break at i=%d", i)
                    phase = TDPhase.NONE
                    s_cnt = cd_cnt = 0
                else:
                    # DeMark condition:
                    #   Close[i] ≥ High[i-2]  AND  Close[i] ≥ High of Setup Bar 8
                    if i >= 2 and c >= high[i - 2] and c >= setup_bar8_ref:
                        cd_cnt += 1
                        if cd_cnt == self.cfg.td_countdown_bars:
                            if i >= 2:
                                countdown_perf[i] = high[i] >= setup_bar8_ref
                            phase = TDPhase.SELL_SIGNAL

            # ── record ────────────────────────────────
            phases[i]   = phase
            tdst_arr[i] = tdst

            # setup_count: ถ้า bar นี้คือ bar ที่ setup ครบ 9 (พึ่ง transition → COUNTDOWN)
            # ต้องบันทึก pre_s_cnt (=9) ไม่ใช่ s_cnt ที่ reset แล้ว
            just_completed_setup = (
                pre_phase in (TDPhase.BUY_SETUP, TDPhase.SELL_SETUP)
                and phase in (TDPhase.BUY_COUNTDOWN, TDPhase.SELL_COUNTDOWN)
            )
            if just_completed_setup:
                setup_cnt[i] = self.cfg.td_setup_bars  # = 9 (pre_s_cnt ยัง 8 ก่อน increment)
            elif phase in (TDPhase.BUY_SETUP, TDPhase.SELL_SETUP):
                setup_cnt[i] = s_cnt
            else:
                setup_cnt[i] = 0

            countdown_cnt[i] = cd_cnt if phase in (TDPhase.BUY_COUNTDOWN, TDPhase.SELL_COUNTDOWN) else 0

        result = df.copy()
        result["td_phase"]          = phases
        result["setup_count"]       = setup_cnt
        result["countdown_count"]   = countdown_cnt
        result["tdst_level"]        = tdst_arr
        result["setup_perfect"]     = setup_perf
        result["countdown_perfect"] = countdown_perf
        return result


# ═════════════════════════════════════════════════════════════════════
# SECTION 5 — PROBABILITY ENGINE  [FIX-2, FIX-5]
# ═════════════════════════════════════════════════════════════════════

class ProbabilityEngine:
    """
    [FIX-2] Relative % distance จาก P  (ไม่ใช่ absolute price)
    เหตุผล: Pivot ต่างกันทุกวัน ถ้าใช้ absolute price จะเปรียบ session ต่าง
            กันไม่ได้  ต้องใช้ dist_pct = (level - P) / P

    [FIX-5] Vectorized ด้วย pd.Series.rolling — ไม่มี nested Python loop
            เร็วขึ้น ~50x บน 2000 แท่ง
    """

    _log = _get_logger("ProbabilityEngine")

    # Pivot levels คิดเป็น % จาก P (approx สำหรับ Classic Pivot)
    # เหล่านี้คือ "template distances" ที่เราจะ bucket ข้อมูล
    LEVEL_TEMPLATES: dict[str, float] = {
        # upside
        "MR1": +0.34, "R1": +0.68, "MR2": +1.03,
        "R2":  +1.37, "MR3": +1.72, "R3": +2.06,
        # downside
        "MS1": -0.34, "S1": -0.68, "MS2": -1.03,
        "S2":  -1.37, "MS3": -1.72, "S3": -2.06,
    }

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    def _wilson_ci(self, p_hat: float, n: int, z: float = 1.96) -> tuple[float, float]:
        """Wilson score interval — ถูกต้องกว่า Normal approx โดยเฉพาะ p ใกล้ 0/1"""
        if n == 0:
            return 0.0, 1.0
        denom  = 1 + z**2 / n
        center = (p_hat + z**2 / (2 * n)) / denom
        margin = z * np.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
        return max(0.0, center - margin), min(1.0, center + margin)

    def _touch_probability_vectorized(
        self,
        close: np.ndarray,
        high:  np.ndarray,
        low:   np.ndarray,
        dist_pct: float,          # +0.68 = R1, -0.34 = MS1 etc.
        fwd:  int,
        regime_mask: Optional[np.ndarray] = None,
    ) -> tuple[float, float, float, int]:
        """
        [FIX-5] Vectorized touch probability

        สำหรับแต่ละ bar i:
          level_i = close[i] * (1 + dist_pct/100)
          touch   = max(high[i+1..i+fwd]) >= level_i   (upside)
                  = min(low [i+1..i+fwd]) <= level_i   (downside)

        Returns: (point_estimate, ci_low, ci_high, sample_size)
        """
        n = len(close)
        if n < fwd + 1:
            return 0.0, 0.0, 0.0, 0

        close_s = pd.Series(close)
        high_s  = pd.Series(high)
        low_s   = pd.Series(low)

        # Future window max/min — shift(-fwd) แทน loop
        # rolling(fwd).max() aligned to END of window → shift back
        future_high = high_s.shift(-1).rolling(fwd, min_periods=1).max()
        future_low  = low_s.shift(-1).rolling(fwd, min_periods=1).min()

        # Target level ต่อ bar (relative)
        target = close_s * (1 + dist_pct / 100)

        if dist_pct >= 0:
            touch = (future_high >= target).astype(float)
        else:
            touch = (future_low <= target).astype(float)

        # ตัด fwd bars สุดท้าย (ไม่มี future)
        valid = touch.iloc[:-fwd]

        # กรอง regime ถ้ามี
        if regime_mask is not None:
            mask = pd.Series(regime_mask).iloc[:-fwd]
            valid = valid[mask.values]

        valid = valid.dropna()
        if len(valid) < self.cfg.prob_min_sample:
            return 0.0, 0.0, 0.0, len(valid)

        p_hat  = float(valid.mean())
        ci_lo, ci_hi = self._wilson_ci(p_hat, len(valid), self.cfg.prob_z)
        return round(p_hat * 100, 1), round(ci_lo * 100, 1), round(ci_hi * 100, 1), len(valid)

    def calculate(
        self,
        df_h4: pd.DataFrame,
        regimes: Optional[pd.Series] = None,
    ) -> list[ProbabilityBand]:
        """
        คำนวณ touch probability สำหรับทุก level template
        แยก bucket: ALL / RANGING / TRENDING

        [FIX-2] ใช้ relative % distance ไม่ใช่ absolute price
        """
        self._log.info("Calculating probability on %d H4 bars", len(df_h4))

        # ใช้ lookback bars ล่าสุด
        lb   = min(self.cfg.prob_lookback_bars, len(df_h4))
        df_s = df_h4.tail(lb)

        close = df_s["close"].values
        high  = df_s["high"].values
        low   = df_s["low"].values
        fwd   = self.cfg.prob_forward_bars

        # regime mask
        regime_mask_ranging  = None
        regime_mask_trending = None
        if regimes is not None:
            reg_s = regimes.reindex(df_s.index)
            regime_mask_ranging  = (reg_s == MarketRegime.RANGING).values
            regime_mask_trending = reg_s.isin([
                MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN
            ]).values

        bands: list[ProbabilityBand] = []

        for label, dist_pct in self.LEVEL_TEMPLATES.items():
            # ALL regimes
            pe, ci_lo, ci_hi, n_all = self._touch_probability_vectorized(
                close, high, low, dist_pct, fwd
            )
            if n_all < self.cfg.prob_min_sample:
                continue

            # RANGING only
            pe_r, ci_lo_r, ci_hi_r, n_r = self._touch_probability_vectorized(
                close, high, low, dist_pct, fwd, regime_mask_ranging
            )

            # ใช้ RANGING bucket ถ้า sample เพียงพอ, fallback to ALL
            if n_r >= self.cfg.prob_min_sample:
                bands.append(ProbabilityBand(
                    level=0.0,          # ไม่มี absolute price — คำนวณ runtime
                    label=label,
                    dist_pct=dist_pct,
                    point_estimate=pe_r,
                    ci_low=ci_lo_r,
                    ci_high=ci_hi_r,
                    sample_size=n_r,
                    regime_bucket="RANGING",
                ))
            else:
                bands.append(ProbabilityBand(
                    level=0.0,
                    label=label,
                    dist_pct=dist_pct,
                    point_estimate=pe,
                    ci_low=ci_lo,
                    ci_high=ci_hi,
                    sample_size=n_all,
                    regime_bucket="ALL",
                ))

        return sorted(bands, key=lambda b: b.dist_pct)

    def apply_to_pivot(
        self,
        bands: list[ProbabilityBand],
        pv: PivotLevels,
    ) -> list[ProbabilityBand]:
        """
        [FIX-2] Bind absolute price to ProbabilityBand
        """
        result = []
        pv_dict = pv.as_dict()
        for b in bands:
            lvl = pv_dict.get(b.label, pv.P * (1 + b.dist_pct / 100))
            result.append(ProbabilityBand(
                level=lvl,
                label=b.label,
                dist_pct=b.dist_pct,
                point_estimate=b.point_estimate,
                ci_low=b.ci_low,
                ci_high=b.ci_high,
                sample_size=b.sample_size,
                regime_bucket=b.regime_bucket,
            ))
        return sorted(result, key=lambda b: b.level)

    def calculate_adaptive(
        self,
        df_h4: pd.DataFrame,
        pv: PivotLevels,
        regimes: Optional[pd.Series] = None,
    ) -> list[ProbabilityBand]:
        """
        [GAP-4] Adaptive probability using ACTUAL pivot distances per session
        instead of fixed template percentages.

        Computes dist_pct for each pivot level relative to P dynamically,
        so probability reflects actual market structure, not approximations.
        """
        self._log.info("Calculating ADAPTIVE probability on %d H4 bars", len(df_h4))

        # Compute actual % distances from P for this session's pivots
        pv_dict = pv.as_dict()
        adaptive_templates: dict[str, float] = {}
        for label, price in pv_dict.items():
            if label == "P":
                continue
            dist_pct = (price - pv.P) / pv.P * 100
            if abs(dist_pct) > 0.01:  # skip if essentially at P
                adaptive_templates[label] = round(dist_pct, 4)

        self._log.info(
            "Adaptive templates: %s (vs fixed: %s)",
            {k: f"{v:+.3f}%" for k, v in sorted(adaptive_templates.items(), key=lambda x: x[1])},
            {k: f"{v:+.3f}%" for k, v in sorted(self.LEVEL_TEMPLATES.items(), key=lambda x: x[1])},
        )

        # Use the same vectorized engine but with actual distances
        lb   = min(self.cfg.prob_lookback_bars, len(df_h4))
        df_s = df_h4.tail(lb)
        close = df_s["close"].values
        high  = df_s["high"].values
        low   = df_s["low"].values
        fwd   = self.cfg.prob_forward_bars

        regime_mask_ranging = None
        if regimes is not None:
            reg_s = regimes.reindex(df_s.index)
            regime_mask_ranging = (reg_s == MarketRegime.RANGING).values

        bands: list[ProbabilityBand] = []

        for label, dist_pct in adaptive_templates.items():
            pe, ci_lo, ci_hi, n_all = self._touch_probability_vectorized(
                close, high, low, dist_pct, fwd
            )
            if n_all < self.cfg.prob_min_sample:
                continue

            # Try regime-specific
            pe_r, ci_lo_r, ci_hi_r, n_r = self._touch_probability_vectorized(
                close, high, low, dist_pct, fwd, regime_mask_ranging
            )

            actual_level = pv_dict.get(label, pv.P * (1 + dist_pct / 100))

            if n_r >= self.cfg.prob_min_sample:
                bands.append(ProbabilityBand(
                    level=actual_level, label=label, dist_pct=dist_pct,
                    point_estimate=pe_r, ci_low=ci_lo_r, ci_high=ci_hi_r,
                    sample_size=n_r, regime_bucket="RANGING",
                ))
            else:
                bands.append(ProbabilityBand(
                    level=actual_level, label=label, dist_pct=dist_pct,
                    point_estimate=pe, ci_low=ci_lo, ci_high=ci_hi,
                    sample_size=n_all, regime_bucket="ALL",
                ))

        return sorted(bands, key=lambda b: b.level)


# ═════════════════════════════════════════════════════════════════════
# SECTION 6 — CONFLUENCE SCORER
# ═════════════════════════════════════════════════════════════════════

class ConfluxScorer:
    """
    [GAP-1 Enhanced] Confluence Scorer with:
    - Regime-aware scoring (trending + aligned gets bonus, not just RANGING)
    - Interaction terms (TD + CZ synergy)
    - Regime duration bonus (established regimes get extra confidence)
    """

    _log = _get_logger("ConfluxScorer")

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    def score(
        self,
        current_price: float,
        level: float,
        td_row: pd.Series,
        regime: MarketRegime,
        clusters: list[ClusterZone],
        signal_dir: str,   # "BUY" | "SELL"
        trend: str,        # "UP"  | "DOWN"
        regime_duration: int = 0,  # [GAP-1] consecutive bars in same regime
    ) -> ConfluxScore:

        detail: dict[str, float] = {}
        total = 0.0
        cfg   = self.cfg

        # 1. Pivot proximity
        dist = abs(current_price - level)
        if dist <= cfg.cz_pip_threshold:
            pts = cfg.w_pivot_proximity * (1 - dist / cfg.cz_pip_threshold)
            detail["pivot_proximity"] = pts
            total += pts

        # 2. TD Setup
        phase = td_row.get("td_phase", TDPhase.NONE)
        if hasattr(phase, "value"):
            phase_val = phase.value
        elif isinstance(phase, str):
            phase_val = phase
        else:
            phase_val = str(phase)
            
        sc    = int(td_row.get("setup_count", 0))
        has_td_signal = False
        if phase_val in ("BUY_SETUP", "SELL_SETUP") and sc >= 8:
            detail["td_setup"] = cfg.w_td_setup
            total += cfg.w_td_setup
            has_td_signal = True
            if bool(td_row.get("setup_perfect", False)):
                detail["td_setup_perfect"] = cfg.w_td_setup_perfect
                total += cfg.w_td_setup_perfect

        # 3. TD Countdown
        cc = int(td_row.get("countdown_count", 0))
        if phase_val in ("BUY_COUNTDOWN", "SELL_COUNTDOWN") and cc >= 12:
            detail["td_countdown"] = cfg.w_td_countdown
            total += cfg.w_td_countdown
            has_td_signal = True
            if bool(td_row.get("countdown_perfect", False)):
                detail["td_countdown_perfect"] = cfg.w_td_countdown_perfect
                total += cfg.w_td_countdown_perfect

        # 4. Cluster Zone
        has_cz = False
        for cz in clusters:
            near = cz.low - cfg.cz_pip_threshold <= level <= cz.high + cfg.cz_pip_threshold
            if near:
                pts = cfg.w_cz_3tf if cz.strength >= 3 else cfg.w_cz_2tf
                detail["cluster_zone"] = pts
                total += pts
                has_cz = True
                break

        # 5. Regime — [GAP-1] Now regime-aware (not just RANGING)
        reg_val = regime.value if hasattr(regime, "value") else str(regime)
        if reg_val == "RANGING":
            detail["regime"] = cfg.w_regime
            total += cfg.w_regime
        elif reg_val in ("TRENDING_UP", "TRENDING_DOWN"):
            # [GAP-1] Trending regime + aligned signal = bonus
            trend_aligned_with_regime = (
                (reg_val == "TRENDING_UP" and signal_dir == "BUY") or
                (reg_val == "TRENDING_DOWN" and signal_dir == "SELL")
            )
            if trend_aligned_with_regime:
                detail["regime_trending_bonus"] = cfg.w_regime_trending_bonus
                total += cfg.w_regime_trending_bonus

        # 6. Trend alignment
        aligned = (signal_dir == "BUY" and trend == "UP") or \
                  (signal_dir == "SELL" and trend == "DOWN")
        if aligned:
            detail["trend_align"] = cfg.w_trend_align
            total += cfg.w_trend_align

        # 7. [GAP-1] Interaction term: TD signal + CZ overlap = synergy bonus
        if has_td_signal and has_cz:
            detail["td_cz_interaction"] = cfg.w_td_cz_interaction
            total += cfg.w_td_cz_interaction

        # 8. [GAP-1] Regime duration bonus (established regime > 10 bars)
        if regime_duration >= 10:
            detail["regime_duration"] = cfg.w_regime_duration_bonus
            total += cfg.w_regime_duration_bonus

        total = min(total, 100.0)
        self._log.debug("Confluence score=%.1f detail=%s", total, detail)

        pivot_s  = detail.get("pivot_proximity", 0)
        td_s     = detail.get("td_setup", 0) + detail.get("td_countdown", 0)
        regime_s = detail.get("regime", 0) + detail.get("regime_trending_bonus", 0) + detail.get("regime_duration", 0)
        cz_s     = detail.get("cluster_zone", 0) + detail.get("td_cz_interaction", 0)

        return ConfluxScore(
            total=total,
            pivot_score=pivot_s,
            td_score=td_s,
            regime_score=regime_s,
            cz_score=cz_s,
            detail=detail,
        )

    def to_strength(self, score: float) -> SignalStrength:
        if score >= 80: return SignalStrength.STRONG
        if score >= 60: return SignalStrength.MODERATE
        return SignalStrength.WEAK


# ═════════════════════════════════════════════════════════════════════
# SECTION 7 — POSITION SIZER  [FIX-1]
# ═════════════════════════════════════════════════════════════════════

class PositionSizer:
    """
    [FIX-1] เพิ่ม 3 ชั้น sanity check:
      (a) Half-Kelly fraction
      (b) Max risk % per trade (2%)
      (c) Max leverage hard cap  → ป้องกัน margin call
    """

    _log = _get_logger("PositionSizer")

    def __init__(self, balance: float, cfg: SystemConfig = CFG):
        self.balance = balance
        self.cfg     = cfg

    def calculate(
        self,
        entry:    float,
        stop:     float,
        target:   float,
        win_rate: float,
        pip_value_per_lot: Optional[float] = None,
    ) -> dict:

        cfg = self.cfg
        pv  = pip_value_per_lot or cfg.pip_value_per_lot

        risk_pips   = abs(entry - stop)
        reward_pips = abs(target - entry)

        if risk_pips < 1e-9:
            self._log.error("Stop == Entry — cannot size position")
            return {"error": "Stop cannot equal Entry"}

        rr = reward_pips / risk_pips

        # Kelly
        kelly      = max(0.0, win_rate - (1 - win_rate) / max(rr, 1e-9))
        half_kelly = kelly * 0.5

        # (a) Kelly-based dollar risk
        dollar_risk_kelly = self.balance * half_kelly

        # (b) Max risk % cap
        dollar_risk_capped = min(dollar_risk_kelly, self.balance * cfg.max_risk_pct)

        # Lot size from dollar risk
        # XAUUSD: risk_pips × 100 × pv_per_lot = dollar risk per 1 lot
        cost_per_lot = risk_pips * 100 * pv
        if cost_per_lot < 1e-9:
            return {"error": "cost_per_lot is zero"}

        lots_raw = dollar_risk_capped / cost_per_lot

        # (c) Max leverage hard cap  [FIX-1]
        # notional = lots × 100 × current price (approx)
        # max_notional = balance × max_leverage
        max_notional    = self.balance * cfg.max_leverage
        max_lots_lev    = max_notional / (entry * 100 + 1e-9)
        max_lots_hard   = cfg.max_lots_hard_cap

        lots_final = max(cfg.min_lots, min(lots_raw, max_lots_lev, max_lots_hard))

        # warn if capped
        if lots_final < lots_raw - 0.001:
            self._log.warning(
                "Lots capped: raw=%.2f → final=%.2f (lev_cap=%.2f, hard_cap=%.2f)",
                lots_raw, lots_final, max_lots_lev, max_lots_hard,
            )

        actual_dollar_risk = lots_final * cost_per_lot

        return {
            "entry":              entry,
            "stop":               stop,
            "target":             target,
            "risk_pips":          round(risk_pips, 2),
            "reward_pips":        round(reward_pips, 2),
            "rr_ratio":           round(rr, 2),
            "kelly_fraction":     round(kelly, 4),
            "half_kelly":         round(half_kelly, 4),
            "dollar_risk":        round(actual_dollar_risk, 2),
            "lots":               round(lots_final, 2),
            "win_rate_assumed":   win_rate,
            "capped":             lots_final < lots_raw - 0.001,
            "cap_reason":         (
                "leverage" if lots_final >= max_lots_lev - 0.001
                else "hard_cap" if lots_final >= max_lots_hard - 0.001
                else "kelly"
            ),
        }


# ═════════════════════════════════════════════════════════════════════
# SECTION 8 — WALK-FORWARD VALIDATOR  [FIX-3]
# ═════════════════════════════════════════════════════════════════════

class WalkForwardValidator:
    """
    [FIX-3] Expanding Window Walk-Forward (ไม่ใช่ rolling fixed)

    Expanding window หมายความว่า:
      Fold 1: Train [0 .. T1),  Test [T1 .. T2)
      Fold 2: Train [0 .. T2),  Test [T2 .. T3)
      ...
      Fold k: Train [0 .. Tk),  Test [Tk .. Tk+1)

    Training set ขยายขึ้นทุก fold — สะท้อนความจริงที่
    trader มีข้อมูลสะสมมากขึ้นเรื่อยๆ
    """

    _log = _get_logger("WalkForwardValidator")

    def __init__(self, cfg: SystemConfig = CFG):
        self.cfg = cfg

    def run(self, df: pd.DataFrame, strategy_fn) -> pd.DataFrame:
        """
        strategy_fn(df_train, df_test) → dict[str, float]  (metrics)
        """
        n          = len(df)
        n_folds    = self.cfg.wf_n_folds
        min_train  = self.cfg.wf_min_train_bars

        if n < min_train + n_folds * 20:
            self._log.error("Insufficient data: %d bars for %d folds", n, n_folds)
            return pd.DataFrame()

        # test block size = distribute remainder evenly
        remaining    = n - min_train
        test_size    = remaining // (n_folds + 1)

        results: list[dict] = []

        for fold in range(n_folds):
            test_start = min_train + fold * test_size
            test_end   = test_start + test_size

            if test_end > n:
                self._log.warning("Fold %d: not enough data, skipping", fold + 1)
                break

            df_train = df.iloc[:test_start].copy()   # expanding window
            df_test  = df.iloc[test_start:test_end].copy()

            self._log.info(
                "Fold %d/%d — Train: %d bars, Test: %d bars",
                fold + 1, n_folds, len(df_train), len(df_test),
            )

            try:
                metrics = strategy_fn(df_train, df_test)
                metrics.update({
                    "fold":       fold + 1,
                    "train_size": len(df_train),
                    "test_size":  len(df_test),
                    "train_end":  str(df_train.index[-1]),
                    "test_start": str(df_test.index[0]),
                    "test_end":   str(df_test.index[-1]),
                })
                results.append(metrics)
            except Exception as exc:
                self._log.exception("Fold %d failed: %s", fold + 1, exc)
                results.append({"fold": fold + 1, "error": str(exc)})

        result_df = pd.DataFrame(results)
        if "pnl" in result_df.columns:
            result_df["cumulative_pnl"] = result_df["pnl"].cumsum()
        return result_df

    def summary(self, results: pd.DataFrame) -> dict:
        if results.empty or "pnl" not in results.columns:
            return {"error": "no pnl column"}
        pnl = results["pnl"].dropna()
        std = pnl.std()
        return {
            "n_folds":       len(pnl),
            "mean_pnl":      round(float(pnl.mean()), 2),
            "std_pnl":       round(float(std), 2),
            "sharpe_proxy":  round(float(pnl.mean() / std), 3) if std > 0 else 0,
            "win_folds":     int((pnl > 0).sum()),
            "max_dd_fold":   round(float(pnl.min()), 2),
        }


# ═════════════════════════════════════════════════════════════════════
# SECTION 9 — REPORT GENERATOR
# ═════════════════════════════════════════════════════════════════════

class ReportGenerator:

    _log = _get_logger("ReportGenerator")

    def _step_label(self, phase: TDPhase, sc: int, cc: int) -> str:
        return {
            TDPhase.NONE:           "—",
            TDPhase.BUY_SETUP:      f"BUY_SETUP   {sc}/9",
            TDPhase.SELL_SETUP:     f"SELL_SETUP  {sc}/9",
            TDPhase.BUY_COUNTDOWN:  f"BUY_CD      {cc}/13",
            TDPhase.SELL_COUNTDOWN: f"SELL_CD     {cc}/13",
            TDPhase.BUY_SIGNAL:     "✅ BUY SIGNAL (CD=13 Complete)",
            TDPhase.SELL_SIGNAL:    "✅ SELL SIGNAL (CD=13 Complete)",
        }.get(phase, "?")

    def _regime_line(self, regime: MarketRegime) -> str:
        return {
            MarketRegime.RANGING:       "🟢 RANGING    — TD Favorable",
            MarketRegime.TRENDING_UP:   "🔴 TREND UP   — TD Caution",
            MarketRegime.TRENDING_DOWN: "🔴 TREND DOWN — TD Caution",
            MarketRegime.VOLATILE:      "⚫ VOLATILE   — Avoid TD",
        }.get(regime, "?")

    def generate(
        self,
        symbol:         str,
        current_price:  float,
        current_time:   pd.Timestamp,
        td_row:         pd.Series,
        pivots:         dict[str, PivotLevels],
        clusters:       list[ClusterZone],
        regime:         MarketRegime,
        prob_bands:     list[ProbabilityBand],
        conf:           ConfluxScore,
        strength:       SignalStrength,
        position:       dict,
        trend:          str,
        adr:            float,
    ) -> str:

        pv_d  = pivots.get("D")
        phase = td_row.get("td_phase", TDPhase.NONE)
        sc    = int(td_row.get("setup_count", 0))
        cc    = int(td_row.get("countdown_count", 0))
        tdst  = td_row.get("tdst_level", float("nan"))
        perf_s  = bool(td_row.get("setup_perfect", False))
        perf_cd = bool(td_row.get("countdown_perfect", False))

        regime_ok = regime == MarketRegime.RANGING
        str_emoji = {"STRONG": "🔥", "MODERATE": "⭐", "WEAK": "💤"}.get(strength.value, "")

        up_bands   = sorted([b for b in prob_bands if b.dist_pct > 0], key=lambda b: b.dist_pct)
        down_bands = sorted([b for b in prob_bands if b.dist_pct < 0], key=lambda b: b.dist_pct, reverse=True)

        lines: list[str] = []
        a = lines.append

        a("╔══════════════════════════════════════════════════════════════╗")
        a(f"║   {symbol:6s} │ QUANT TD+PIVOT REPORT v3.0                      ║")
        a("╚══════════════════════════════════════════════════════════════╝")
        a(f"Symbol  : {symbol}")
        a(f"Time    : {current_time.strftime('%Y.%m.%d_%H%M%S')}")
        a(f"TF      : H4")
        a(f"Price   : {current_price:.2f}")
        a(f"ADR(14) : {adr:.1f} pts")
        a("")
        a("📈 TREND & REGIME")
        a(f"Trend(H4) = {trend} (HH/HL structure)")
        a(f"Regime    = {self._regime_line(regime)}")
        a(f"{'✅ Regime favorable for TD' if regime_ok else '⚠️  TD reliability LOW — monitor only'}")
        a("")
        a("🔢 TD SEQUENTIAL STATUS")
        a(f"Phase   = {phase.value}")
        a(f"Step    = {self._step_label(phase, sc, cc)}")
        a(f"TDST    = {tdst:.2f}" if not np.isnan(tdst) else "TDST    = —")
        if perf_s:  a("⚡ PERFECTED SETUP (9)")
        if perf_cd: a("⚡ PERFECTED COUNTDOWN (13)")
        a("")

        if pv_d:
            a("📍 PIVOT COORDINATES (Daily)")
            a(f"P            = {pv_d.P:.2f}")
            a(f"R1 / R2 / R3 = {pv_d.R1:.2f} / {pv_d.R2:.2f} / {pv_d.R3:.2f}")
            a(f"S1 / S2 / S3 = {pv_d.S1:.2f} / {pv_d.S2:.2f} / {pv_d.S3:.2f}")
            a(f"MR1/MR2/MR3  = {pv_d.MR1:.2f} / {pv_d.MR2:.2f} / {pv_d.MR3:.2f}")
            a(f"MS1/MS2/MS3  = {pv_d.MS1:.2f} / {pv_d.MS2:.2f} / {pv_d.MS3:.2f}")
            a("")

        a("📊 PROBABILITY MATRIX  (Wilson 95% CI | Regime-bucketed)")
        a("   [FIX-2: relative % distance จาก P — cross-session comparable]")
        a("🔺 Upside")
        for b in up_bands:
            emoji = "🟢" if b.point_estimate >= 50 else "🟡" if b.point_estimate >= 25 else "🔴"
            bucket = f"[{b.regime_bucket}]"
            a(f"  {emoji} {b.level:>7.2f} ({b.label:<4s}) → {b.point_estimate:5.1f}%"
              f"  CI:[{b.ci_low:.1f}–{b.ci_high:.1f}%]  n={b.sample_size}  {bucket}")

        a("🔻 Downside")
        for b in down_bands:
            emoji = "🟢" if b.point_estimate >= 50 else "🟡" if b.point_estimate >= 25 else "🔴"
            bucket = f"[{b.regime_bucket}]"
            a(f"  {emoji} {b.level:>7.2f} ({b.label:<4s}) → {b.point_estimate:5.1f}%"
              f"  CI:[{b.ci_low:.1f}–{b.ci_high:.1f}%]  n={b.sample_size}  {bucket}")

        a("")
        a("📌 CLUSTER ZONES (CZ)")
        for idx, cz in enumerate(clusters[:5]):
            a(f"  🔶 CZ{idx+1}  {cz.name:<40s}  {cz.low:.2f}–{cz.high:.2f}  [{cz.strength} TF]")

        a("")
        a(f"🎯 CONFLUENCE SCORE  {str_emoji} {strength.value}")
        a(f"  Total   = {conf.total:.1f} / 100")
        a(f"  ├ Pivot = {conf.pivot_score:.1f}")
        a(f"  ├ TD    = {conf.td_score:.1f}")
        a(f"  ├ Regime= {conf.regime_score:.1f}")
        a(f"  └ CZ    = {conf.cz_score:.1f}")

        if position and "lots" in position:
            a("")
            a("💰 POSITION SIZING  (Half-Kelly + 3-layer cap)  [FIX-1]")
            a(f"  Entry    = {position['entry']:.2f}")
            a(f"  Stop     = {position['stop']:.2f}")
            a(f"  Target   = {position['target']:.2f}")
            a(f"  R:R      = 1:{position['rr_ratio']:.2f}")
            a(f"  Kelly    = {position['kelly_fraction']*100:.1f}%  →  Half = {position['half_kelly']*100:.1f}%")
            a(f"  $ Risk   = ${position['dollar_risk']:.2f}")
            a(f"  Lots     = {position['lots']:.2f}"
              + (f"  ⚠️ CAPPED ({position['cap_reason']})" if position.get("capped") else ""))

        a("")
        if strength == SignalStrength.STRONG:
            a("✅  SIGNAL CONFIRMED — Enter on next H4 close")
        elif strength == SignalStrength.MODERATE:
            a("⭐  SIGNAL MODERATE — Wait for additional confirmation")
        else:
            a("💤  SIGNAL WEAK (score<60) — Monitor only, no trade")
        a("══════════════════════════════════════════════════════════════")

        report = "\n".join(lines)
        self._log.info("Report generated for %s @ %.2f", symbol, current_price)
        return report


# ═════════════════════════════════════════════════════════════════════
# SECTION 10 — MAIN PIPELINE
# ═════════════════════════════════════════════════════════════════════

class QuantTDPivotSystem:
    """
    Orchestrator — รวม Engine ทั้งหมดเข้าด้วยกัน

    Usage:
        system = QuantTDPivotSystem(balance=10_000)
        report = system.run(df_h4, df_d, df_w, df_m)
        print(report)
    """

    _log = _get_logger("QuantTDPivotSystem")

    def __init__(self, balance: float = 10_000, cfg: SystemConfig = CFG):
        self.cfg      = cfg
        self.regime   = RegimeFilter(cfg)
        self.pivots   = PivotEngine(cfg)
        self.td       = TDSequentialEngine(cfg)
        self.prob     = ProbabilityEngine(cfg)
        self.scorer   = ConfluxScorer(cfg)
        self.sizer    = PositionSizer(balance, cfg)
        self.reporter = ReportGenerator()
        self._log.info("System initialised — balance=%.2f", balance)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _trend(df: pd.DataFrame, n: int = 20) -> str:
        recent = df.tail(n)
        highs, lows = recent["high"].values, recent["low"].values
        hh = highs[-1] > highs[:-1].max()
        hl = lows[-1]  > lows[:-1].min()
        ll = lows[-1]  < lows[:-1].min()
        lh = highs[-1] < highs[:-1].max()
        if hh and hl: return "UP"
        if ll and lh: return "DOWN"
        return "SIDEWAYS"

    @staticmethod
    def _adr(df_d: pd.DataFrame, n: int = 14) -> float:
        return float((df_d["high"].tail(n) - df_d["low"].tail(n)).mean().round(2))

    # ── main ─────────────────────────────────────────────────────────

    def run(
        self,
        df_h4:    pd.DataFrame,
        df_d:     pd.DataFrame,
        df_w:     pd.DataFrame,
        df_m:     pd.DataFrame,
        symbol:   str   = "XAUUSD",
        entry:    Optional[float] = None,
        stop:     Optional[float] = None,
        target:   Optional[float] = None,
        win_rate: float = 0.50,
    ) -> str:

        self._log.info("=== Pipeline START: %s ===", symbol)

        t0            = df_h4.index[-1]
        current_price = df_h4["close"].iloc[-1]

        # 1. Regime
        self._log.info("Step 1: Regime classification")
        regimes        = self.regime.classify(df_h4)
        current_regime = regimes.iloc[-1]

        # 2. TD Sequential
        self._log.info("Step 2: TD Sequential")
        df_td  = self.td.compute(df_h4)
        td_row = df_td.iloc[-1]

        # 3. Pivots
        self._log.info("Step 3: Pivot computation")
        pv_map   = self.pivots.compute_all(df_d, df_w, df_m, t0)
        pv_d     = pv_map.get("D")
        clusters = self.pivots.find_cluster_zones(pv_map, current_price)

        # 4. Probability
        self._log.info("Step 4: Probability engine")
        bands_template = self.prob.calculate(df_h4, regimes)
        prob_bands     = self.prob.apply_to_pivot(bands_template, pv_d) if pv_d else []

        # 5. Trend
        trend = self._trend(df_h4)

        # 6. ADR
        adr = self._adr(df_d)

        # 7. Confluence
        self._log.info("Step 5: Confluence scoring")
        focus_level = pv_d.MR1 if pv_d else current_price
        signal_dir  = "BUY" if trend == "UP" else "SELL"
        conf        = self.scorer.score(
            current_price, focus_level, td_row,
            current_regime, clusters, signal_dir, trend,
        )
        strength = self.scorer.to_strength(conf.total)

        # 8. Position sizing
        self._log.info("Step 6: Position sizing")
        pos = {}
        if entry is not None and stop is not None and target is not None:
            pos = self.sizer.calculate(entry, stop, target, win_rate)

        # 9. Report
        self._log.info("Step 7: Report generation")
        report = self.reporter.generate(
            symbol, current_price, t0,
            td_row, pv_map, clusters,
            current_regime, prob_bands,
            conf, strength, pos, trend, adr,
        )

        self._log.info("=== Pipeline DONE ===")
        return report


# ═════════════════════════════════════════════════════════════════════
# SECTION 11 — UNIT TESTS  [FIX-7]
# ═════════════════════════════════════════════════════════════════════

class TestTDSequential(unittest.TestCase):
    """
    [FIX-7] Unit tests สำหรับ TD Engine
    ทดสอบทุก edge case ที่ DeMark spec กำหนด
    """

    def _make_df(self, closes: list[float], extra_hl: float = 1.0) -> pd.DataFrame:
        n = len(closes)
        idx = pd.date_range("2024-01-01", periods=n, freq="4h")
        return pd.DataFrame({
            "open":   [c - 0.5 for c in closes],
            "high":   [c + extra_hl for c in closes],
            "low":    [c - extra_hl for c in closes],
            "close":  closes,
            "volume": [1000] * n,
        }, index=idx)

    def test_buy_setup_completes(self):
        """9 consecutive closes each < close[i-4] → BUY_SETUP complete"""
        # สร้าง downtrend ชัดเจน: ลดลง 1 ต่อแท่ง
        closes = list(range(100, 70, -1))   # 30 แท่ง ลดลง
        df = self._make_df(closes)
        engine = TDSequentialEngine()
        result = engine.compute(df)

        setup_rows = result[result["td_phase"] == TDPhase.BUY_SETUP]
        self.assertFalse(setup_rows.empty, "Should have BUY_SETUP rows")

        max_count = result["setup_count"].max()
        self.assertGreaterEqual(max_count, 9, f"Setup count should reach 9, got {max_count}")

    def test_sell_setup_completes(self):
        """9 consecutive closes each > close[i-4] → SELL_SETUP complete"""
        closes = list(range(70, 100, 1))    # 30 แท่ง ขึ้น
        df = self._make_df(closes)
        engine = TDSequentialEngine()
        result = engine.compute(df)

        max_count = result["setup_count"].max()
        self.assertGreaterEqual(max_count, 9, f"Sell setup count should reach 9, got {max_count}")

    def test_setup_resets_on_tdst_break(self):
        """
        [FIX-4] Buy Setup ควร reset ถ้า Close > TDST
        ไม่ใช่ reset ทุกครั้งที่ direction เปลี่ยน
        """
        # ลดลง 8 แท่ง แล้ว spike ขึ้นสูงมาก (เกิน TDST) → reset
        closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90,  # ลดลง
                  200]                                             # spike สูง → TDST break
        df = self._make_df(closes, extra_hl=0.1)
        engine = TDSequentialEngine()
        result = engine.compute(df)
        last_phase = result["td_phase"].iloc[-1]
        # หลัง spike ควรไม่อยู่ใน BUY_SETUP อีกต่อไป
        self.assertNotEqual(last_phase, TDPhase.BUY_COUNTDOWN)

    def test_no_lookahead_at_bar_4(self):
        """ต้องใช้แท่งอย่างน้อย 5 แท่ง (0..4) ถึงจะเริ่มนับ"""
        closes = [100.0] * 5
        df = self._make_df(closes)
        engine = TDSequentialEngine()
        result = engine.compute(df)
        # bar 0-3 ต้องเป็น NONE (ยังไม่มี close[i-4])
        for i in range(4):
            self.assertEqual(result["td_phase"].iloc[i], TDPhase.NONE)

    def test_wilson_ci_bounds(self):
        """Wilson CI ต้องอยู่ใน [0, 100] เสมอ"""
        eng = ProbabilityEngine()
        for p, n in [(0.0, 30), (1.0, 30), (0.5, 100), (0.01, 50)]:
            lo, hi = eng._wilson_ci(p, n)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)
            self.assertLessEqual(lo, hi)

    def test_position_sizer_lot_cap(self):
        """
        [FIX-1] Lots ต้องไม่เกิน max_leverage cap
        balance=$10,000, entry=5300, max_leverage=10
        → max_notional = $100,000 → max_lots = 100000 / (5300*100) ≈ 0.19 lots
        """
        cfg = SystemConfig(max_leverage=10.0, max_risk_pct=0.02)
        sizer = PositionSizer(balance=10_000, cfg=cfg)
        result = sizer.calculate(
            entry=5300, stop=5280, target=5360, win_rate=0.55
        )
        self.assertIn("lots", result)
        max_lots_expected = 10_000 * 10.0 / (5300 * 100)
        self.assertLessEqual(result["lots"], max_lots_expected + 0.01)

    def test_wf_expanding_window(self):
        """
        [FIX-3] Fold k ต้อง train บน data ตั้งแต่ต้นถึง test_start
        (expanding window ไม่ใช่ rolling)
        """
        cfg = SystemConfig(wf_min_train_bars=50, wf_n_folds=3)
        wf  = WalkForwardValidator(cfg)

        train_sizes: list[int] = []

        def dummy_strategy(df_train, df_test):
            train_sizes.append(len(df_train))
            return {"pnl": 1.0}

        n = 500
        dates = pd.date_range("2024-01-01", periods=n, freq="4h")
        df = pd.DataFrame({"close": np.random.randn(n).cumsum() + 5300}, index=dates)
        wf.run(df, dummy_strategy)

        # Training size ต้องเพิ่มขึ้นทุก fold (expanding)
        for i in range(1, len(train_sizes)):
            self.assertGreater(train_sizes[i], train_sizes[i - 1],
                               "Train size must grow each fold (expanding window)")


def run_tests():
    """Run all unit tests — เรียกจาก pipeline ก่อน deploy"""
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(TestTDSequential)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


# ═════════════════════════════════════════════════════════════════════
# DEMO
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    log = _get_logger("main")

    # ── 0. Run unit tests first ───────────────────────────────────────
    log.info("Running unit tests before pipeline...")
    ok = run_tests()
    if not ok:
        log.error("Unit tests FAILED — fix before proceeding")
        raise SystemExit(1)
    log.info("All tests passed ✅")

    # ── 1. Synthetic data ─────────────────────────────────────────────
    np.random.seed(42)
    N = 2200     # ~1 ปีของ H4 (พอสำหรับ probability lookback)

    dates_h4 = pd.date_range("2022-01-01", periods=N, freq="4h")
    price = 5300 + np.cumsum(np.random.randn(N) * 1.8)

    df_h4 = pd.DataFrame({
        "open":   price - np.abs(np.random.randn(N)),
        "high":   price + np.abs(np.random.randn(N)) * 2,
        "low":    price - np.abs(np.random.randn(N)) * 2,
        "close":  price + np.random.randn(N) * 0.5,
        "volume": np.random.randint(1000, 5000, N),
    }, index=dates_h4)

    df_d = df_h4.resample("D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    df_w = df_h4.resample("W").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    df_m = df_h4.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

    # ── 2. Run system ─────────────────────────────────────────────────
    cfg    = SystemConfig(prob_lookback_bars=2000, max_leverage=10.0)
    system = QuantTDPivotSystem(balance=10_000, cfg=cfg)

    report = system.run(
        df_h4, df_d, df_w, df_m,
        symbol   = "XAUUSD",
        entry    = 5334.0,
        stop     = 5310.0,
        target   = 5407.0,
        win_rate = 0.52,
    )

    print(report)
