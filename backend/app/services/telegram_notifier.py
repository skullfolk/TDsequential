"""
Telegram Notifier Service
Sends the 4H analysis report summary to a Telegram chat.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not set — notifications disabled")

    def _url(self) -> str:
        return TELEGRAM_API_BASE.format(token=self.token)

    def _is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        """Send a plain or Markdown message. Returns True on success."""
        if not self._is_configured():
            logger.warning("Telegram not configured, skipping notification")
            return False
        try:
            # Use a short timeout and run in best-effort mode
            # to avoid blocking the scheduler thread
            from concurrent.futures import ThreadPoolExecutor
            def _do_send():
                try:
                    resp = httpx.post(
                        self._url(),
                        json={
                            "chat_id": self.chat_id,
                            "text": text,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                        timeout=10,
                    )
                    resp.raise_for_status()
                    logger.info("Telegram message sent (chat_id=%s)", self.chat_id)
                except Exception as exc:
                    logger.error("Telegram send failed: %s", exc)
            ThreadPoolExecutor(max_workers=1).submit(_do_send)
            return True
        except Exception as exc:
            logger.error("Telegram send scheduling failed: %s", exc)
            return False

    def send_report(self, report: dict) -> bool:
        """Format and send the analysis report as a Telegram message."""
        meta   = report.get("meta", {})
        trend  = report.get("trend_regime", {})
        td     = report.get("td_status", {})
        conf   = report.get("confluence", {})
        ctx    = report.get("context", {})
        prob   = report.get("probabilities", {})

        sym   = meta.get("symbol", "XAUUSD")
        price = meta.get("current_price", 0)
        ts    = meta.get("timestamp", "")
        strength = conf.get("strength", "N/A")
        score    = conf.get("total_score", 0)

        # Build top upside/downside lines
        upside_lines = ""
        for b in (prob.get("upside") or [])[:3]:
            emoji = "🟢" if b["point_estimate"] >= 50 else "🟡" if b["point_estimate"] >= 25 else "🔴"
            upside_lines += f"  {emoji} {b['level']:.0f} ({b['label']}) → {b['point_estimate']:.1f}%\n"

        downside_lines = ""
        for b in (prob.get("downside") or [])[:3]:
            emoji = "🟢" if b["point_estimate"] >= 50 else "🟡" if b["point_estimate"] >= 25 else "🔴"
            downside_lines += f"  {emoji} {b['level']:.0f} ({b['label']}) → {b['point_estimate']:.1f}%\n"

        strength_emoji = {"STRONG": "🔥", "MODERATE": "⭐", "WEAK": "💤"}.get(strength, "")

        msg = (
            f"📊 *{sym} — Quant TD+Pivot Report (H4)*\n"
            f"🕐 `{ts}`\n\n"
            f"💰 Price: `{price:.2f}`\n"
            f"📈 Trend: `{trend.get('trend', 'N/A')}` | Regime: `{trend.get('regime', 'N/A')}`\n"
            f"📍 Context: `{ctx.get('zone', 'N/A')}` → {ctx.get('bias', '')}\n"
            f"🔢 TD Phase: `{td.get('phase', 'N/A')}` ({td.get('setup_count', 0)}/{td.get('countdown_count', 0)})\n\n"
            f"🎯 Confluence: {strength_emoji} *{strength}* ({score:.1f}/100)\n\n"
            f"🔺 *Upside Prob*\n{upside_lines}"
            f"🔻 *Downside Prob*\n{downside_lines}"
        )

        return self.send(msg)


# Singleton
notifier = TelegramNotifier()
