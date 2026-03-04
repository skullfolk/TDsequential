"""
Database models using SQLModel (SQLAlchemy + Pydantic).
Tables: symbol_watchlist, analysis_history, user_profile_settings
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session


# ─── Table 1: Symbol Watchlist ────────────────────────────────────────────────

class SymbolWatchlist(SQLModel, table=True):
    __tablename__ = "symbol_watchlist"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, unique=True)      # e.g. "XAUUSD=X"
    display_name: str = Field(default="XAUUSD")       # e.g. "XAUUSD"
    asset_class: str = Field(default="FOREX")          # "FOREX" | "CRYPTO"
    is_active: bool = Field(default=True)


# ─── Table 2: Analysis History ────────────────────────────────────────────────

class AnalysisHistory(SQLModel, table=True):
    __tablename__ = "analysis_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol_id: int = Field(foreign_key="symbol_watchlist.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Key metrics (indexed for quick history queries)
    current_price: float
    trend: str            # "UP" | "DOWN" | "SIDEWAYS"
    regime: str           # "RANGING" | "TRENDING_UP" | ...
    td_phase: str
    context_zone: str     # "P-MR1" | "MR1-R1" | ...
    confluence_score: float
    signal_strength: str  # "STRONG" | "MODERATE" | "WEAK"
    vr: float             # Volatility Ratio
    reach_cl: float       # % Reach vs ADR

    # Full structured JSON blob for all detail (pivot levels, prob bands, CZ, etc.)
    raw_report_json: str = Field(default="{}")

    def set_report(self, data: dict) -> None:
        self.raw_report_json = json.dumps(data, default=str)

    def get_report(self) -> dict:
        return json.loads(self.raw_report_json)


# ─── Table 3: User Profile / Position Sizing Preferences ─────────────────────

class UserProfileSettings(SQLModel, table=True):
    __tablename__ = "user_profile_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    default_balance: float = Field(default=10_000.0)
    max_risk_pct: float   = Field(default=2.0)      # % per trade
    max_leverage: float   = Field(default=10.0)
    pip_value_per_lot: float = Field(default=1.0)
    min_lots: float       = Field(default=0.01)
    max_lots_hard_cap: float = Field(default=50.0)


# ─── Engine & helpers ─────────────────────────────────────────────────────────

def get_engine(db_url: str = "sqlite:///./quant_report.db"):
    return create_engine(db_url, echo=False, connect_args={"check_same_thread": False})


def create_tables(engine) -> None:
    SQLModel.metadata.create_all(engine)


def seed_defaults(engine) -> None:
    """Insert default symbol and profile rows if not present."""
    from sqlmodel import select
    with Session(engine) as session:
        existing_sym = session.exec(
            select(SymbolWatchlist).where(SymbolWatchlist.symbol == "XAUUSD=X")
        ).first()
        if not existing_sym:
            session.add(SymbolWatchlist(
                symbol="XAUUSD=X",
                display_name="XAUUSD",
                asset_class="FOREX",
                is_active=True,
            ))

        existing_profile = session.exec(select(UserProfileSettings)).first()
        if not existing_profile:
            session.add(UserProfileSettings())

        session.commit()
