"""
BTC Global Elite Scalper V6 — Professional Telegram Alert System
Premium formatted notifications for all bot events.
"""

import logging
from datetime import datetime, timezone

import requests

import config

logger = logging.getLogger("Alerts")


class AlertSystem:
    """Professional Telegram notification engine."""

    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.warning(
                "Telegram alerts DISABLED — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

    def _send(self, text):
        """Send message via Telegram Bot API with HTML formatting."""
        if not self.enabled:
            logger.info(f"[ALERT] {text}")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Telegram send failed: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def _timestamp(self):
        """Current UTC time formatted."""
        return datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M UTC")

    # ---------------------------------------------------------------
    # STARTUP / SHUTDOWN
    # ---------------------------------------------------------------
    def send_startup_alert(self, wallet_balance=0, product_id=None):
        """Send professional startup message when bot deploys."""
        self._send(
            f"{'='*28}\n"
            f"<b>BTC GLOBAL ELITE SCALPER V6</b>\n"
            f"{'='*28}\n\n"
            f"<b>STATUS:</b> ONLINE\n"
            f"<b>MODE:</b> {config.MODE.upper()}\n\n"
            f"<b>CONFIGURATION</b>\n"
            f"<b>Symbol:</b> {config.SYMBOL}\n"
            f"<b>Timeframe:</b> {config.TIMEFRAME}\n"
            f"<b>Leverage:</b> {config.LEVERAGE}x\n"
            f"<b>Margin:</b> {config.MARGIN_PERCENT*100:.0f}%\n\n"
            f"<b>STRATEGY</b>\n"
            f"<b>UT Bot:</b> ATR({config.UT_BOT_ATR_PERIOD}) x {config.UT_BOT_KEY_VALUE}\n"
            f"<b>STC:</b> Cycle({config.STC_CYCLE_LENGTH})\n"
            f"<b>Trend:</b> EMA {config.EMA_PERIOD}\n\n"
            f"<b>RISK MANAGEMENT</b>\n"
            f"<b>Max Drawdown:</b> {config.MAX_DAILY_DRAWDOWN*100:.0f}%/day\n"
            f"<b>Max Trades:</b> {config.MAX_ACTIVE_TRADES}\n"
            f"<b>Timeout:</b> {config.TIMEOUT_MINUTES} min\n\n"
            f"<b>ACCOUNT</b>\n"
            f"<b>Balance:</b> ${wallet_balance:.2f}\n"
            f"<b>Product ID:</b> {product_id}\n\n"
            f"<b>Bot is now scanning for signals...</b>\n"
            f"<i>{self._timestamp()}</i>"
        )

    def send_shutdown_alert(self, reason="Manual shutdown"):
        """Notify when bot stops."""
        self._send(
            f"<b>BOT OFFLINE</b>\n\n"
            f"<b>Reason:</b> {reason}\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # TRADE ENTRY
    # ---------------------------------------------------------------
    def send_entry_alert(self, side, price, size, signal_info=None, attempt=1):
        """Professional trade entry notification."""
        is_long = side.lower() == "buy"
        arrow = "LONG" if is_long else "SHORT"

        stc = signal_info.get("stc", 0) if signal_info else 0
        ema = signal_info.get("ema200", 0) if signal_info else 0

        self._send(
            f"{'='*28}\n"
            f"<b>NEW {arrow} POSITION OPENED</b>\n"
            f"{'='*28}\n\n"
            f"<b>Side:</b> {arrow}\n"
            f"<b>Entry Price:</b> ${price:,.2f}\n"
            f"<b>Size:</b> {size} contracts\n"
            f"<b>Leverage:</b> {config.LEVERAGE}x\n"
            f"<b>Fill Attempt:</b> {attempt}/{config.CHASE_MAX_ATTEMPTS}\n\n"
            f"<b>SIGNAL CONFLUENCE</b>\n"
            f"<b>UT Bot:</b> {'BUY' if is_long else 'SELL'}\n"
            f"<b>STC:</b> {stc:.1f}\n"
            f"<b>EMA {config.EMA_PERIOD}:</b> ${ema:,.2f}\n"
            f"<b>Trend:</b> {'Bullish' if is_long else 'Bearish'}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # TRADE EXIT
    # ---------------------------------------------------------------
    def send_exit_alert(self, side, entry_price, exit_price, pnl, pnl_pct, reason):
        """Professional trade exit notification."""
        is_profit = pnl >= 0
        result = "PROFIT" if is_profit else "LOSS"

        self._send(
            f"{'='*28}\n"
            f"<b>POSITION CLOSED — {result}</b>\n"
            f"{'='*28}\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>Exit:</b> ${exit_price:,.2f}\n"
            f"<b>Move:</b> {abs(exit_price-entry_price):,.2f} pts\n\n"
            f"<b>RESULT</b>\n"
            f"<b>P&L:</b> {'+'if is_profit else ''}{pnl_pct*100:.2f}%\n"
            f"<b>USD:</b> {'+'if is_profit else ''}${pnl:.4f}\n"
            f"<b>Reason:</b> {reason}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # PARTIAL TAKE PROFIT
    # ---------------------------------------------------------------
    def send_partial_tp_alert(self, side, entry_price, exit_price, profit_pct):
        """Partial TP notification."""
        self._send(
            f"{'='*28}\n"
            f"<b>PARTIAL TAKE PROFIT (50%)</b>\n"
            f"{'='*28}\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>TP Hit:</b> ${exit_price:,.2f}\n"
            f"<b>Locked Profit:</b> +{profit_pct*100:.2f}%\n\n"
            f"<b>Remaining 50% riding with Trailing SL</b>\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # BREAKEVEN
    # ---------------------------------------------------------------
    def send_breakeven_alert(self, side, entry_price):
        """SL moved to breakeven notification."""
        self._send(
            f"<b>STOP LOSS MOVED TO BREAKEVEN</b>\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>SL Price:</b> ${entry_price:,.2f} (entry)\n"
            f"<b>Risk:</b> ZERO\n\n"
            f"<i>Trade is now risk-free</i>\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # STOP LOSS
    # ---------------------------------------------------------------
    def send_sl_hit_alert(self, side, entry_price, sl_price, pnl_pct):
        """Stop loss hit notification."""
        self._send(
            f"{'='*28}\n"
            f"<b>STOP LOSS TRIGGERED</b>\n"
            f"{'='*28}\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>SL Hit:</b> ${sl_price:,.2f}\n"
            f"<b>P&L:</b> {pnl_pct*100:.2f}%\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # TRAILING SL
    # ---------------------------------------------------------------
    def send_trailing_sl_alert(self, side, entry_price, exit_price, pnl_pct):
        """Trailing SL exit notification."""
        self._send(
            f"{'='*28}\n"
            f"<b>TRAILING STOP TRIGGERED</b>\n"
            f"{'='*28}\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>Exit:</b> ${exit_price:,.2f}\n"
            f"<b>P&L:</b> {'+'if pnl_pct>=0 else ''}{pnl_pct*100:.2f}%\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # BOT LOCKED
    # ---------------------------------------------------------------
    def send_lock_alert(self, reason):
        """Bot locked due to drawdown."""
        self._send(
            f"{'='*28}\n"
            f"<b>BOT LOCKED — DRAWDOWN LIMIT</b>\n"
            f"{'='*28}\n\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Duration:</b> {config.DAILY_LOCK_HOURS} hours\n\n"
            f"<i>Bot will auto-unlock after cooldown period</i>\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # SAFETY BLOCK
    # ---------------------------------------------------------------
    def send_safety_block_alert(self, reason):
        """Trade blocked by safety filter."""
        self._send(
            f"<b>TRADE BLOCKED — SAFETY FILTER</b>\n\n"
            f"<b>Reason:</b> {reason}\n\n"
            f"<i>Bot continues scanning...</i>\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # SIGNAL DETECTED (No Entry)
    # ---------------------------------------------------------------
    def send_signal_detected(self, signal, price, stc, ema200, reason=""):
        """Signal detected but conditions not fully met."""
        self._send(
            f"<b>SIGNAL DETECTED — NO ENTRY</b>\n\n"
            f"<b>Signal:</b> {signal}\n"
            f"<b>Price:</b> ${price:,.2f}\n"
            f"<b>STC:</b> {stc:.1f}\n"
            f"<b>EMA200:</b> ${ema200:,.2f}\n"
            f"<b>Note:</b> {reason}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # STATUS / ERROR
    # ---------------------------------------------------------------
    def send_status(self, message):
        """General status update."""
        self._send(
            f"<b>STATUS UPDATE</b>\n\n"
            f"{message}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    def send_error(self, error):
        """Error notification."""
        self._send(
            f"{'='*28}\n"
            f"<b>ERROR DETECTED</b>\n"
            f"{'='*28}\n\n"
            f"<b>Details:</b> {str(error)[:200]}\n\n"
            f"<i>Bot will attempt to recover...</i>\n"
            f"<i>{self._timestamp()}</i>"
        )
