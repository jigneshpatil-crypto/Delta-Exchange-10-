"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Professional Telegram Alert System
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
            f"{'='*32}\n"
            f"<b>HA + CHANDELIER EXIT + LSMA BOT</b>\n"
            f"{'='*32}\n\n"
            f"<b>STATUS:</b> ONLINE ✅\n"
            f"<b>MODE:</b> {config.MODE.upper()}\n\n"
            f"<b>STRATEGY</b>\n"
            f"<b>Name:</b> {config.STRATEGY_NAME}\n"
            f"<b>Symbol:</b> {config.SYMBOL}\n"
            f"<b>Timeframe:</b> {config.TIMEFRAME}\n"
            f"<b>Direction:</b> {config.TRADE_DIRECTION} ONLY\n"
            f"<b>Leverage:</b> {config.LEVERAGE}x Isolated\n\n"
            f"<b>INDICATORS</b>\n"
            f"<b>Chandelier Exit:</b> ATR({config.CE_ATR_PERIOD}) x {config.CE_ATR_MULTIPLIER}\n"
            f"<b>LSMA:</b> Period {config.LSMA_PERIOD}\n"
            f"<b>Heikin-Ashi:</b> Candle color for exit\n\n"
            f"<b>EXECUTION RULES</b>\n"
            f"<b>Order Type:</b> MARKET ONLY (instant execution)\n"
            f"<b>Entry Timeout:</b> None (Market Orders)\n"
            f"<b>Hard SL:</b> {config.HARD_STOP_LOSS_PCT*100}% (emergency)\n"
            f"<b>Pyramiding:</b> {config.PYRAMIDING} (strict)\n\n"
            f"<b>RISK MANAGEMENT</b>\n"
            f"<b>Capital/Trade:</b> ${config.CAPITAL_PER_TRADE}\n"
            f"<b>Daily Drawdown:</b> {config.MAX_DAILY_DRAWDOWN*100:.0f}% → 24h pause\n\n"
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
    # STRATEGY DEPLOYMENT
    # ---------------------------------------------------------------
    def send_deployment_alert(self, old_removed=True, new_deployed=True, sample_result=""):
        """Deployment confirmation alert."""
        self._send(
            f"{'='*32}\n"
            f"<b>STRATEGY DEPLOYMENT REPORT</b>\n"
            f"{'='*32}\n\n"
            f"<b>Old Strategy:</b> {'✅ Removed' if old_removed else '❌ Failed'}\n"
            f"<b>New Strategy:</b> {'✅ Deployed' if new_deployed else '❌ Failed'}\n"
            f"<b>Strategy:</b> {config.STRATEGY_NAME}\n\n"
            f"<b>SAMPLE TRADE:</b>\n"
            f"{sample_result}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # TRADE ENTRY
    # ---------------------------------------------------------------
    def send_entry_alert(self, side, price, size, signal_info=None):
        """Professional trade entry notification."""
        self._send(
            f"{'='*32}\n"
            f"<b>NEW LONG POSITION OPENED</b>\n"
            f"{'='*32}\n\n"
            f"<b>Side:</b> LONG (Buy)\n"
            f"<b>Entry Price:</b> ${price:,.2f}\n"
            f"<b>Size:</b> {size} contracts\n"
            f"<b>Leverage:</b> {config.LEVERAGE}x Isolated\n"
            f"<b>Order Type:</b> LIMIT ✅\n\n"
            f"<b>SIGNAL</b>\n"
            f"<b>Chandelier Exit:</b> Flipped GREEN 🟢\n"
            f"<b>LSMA {config.LSMA_PERIOD}:</b> Close > LSMA\n"
            f"<b>Hard SL:</b> ${price * (1 - config.HARD_STOP_LOSS_PCT):,.2f} "
            f"(-{config.HARD_STOP_LOSS_PCT*100}%)\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # TRADE EXIT
    # ---------------------------------------------------------------
    def send_exit_alert(self, side, entry_price, exit_price, pnl, pnl_pct, reason):
        """Professional trade exit notification."""
        is_profit = pnl >= 0
        result = "PROFIT ✅" if is_profit else "LOSS ❌"

        self._send(
            f"{'='*32}\n"
            f"<b>POSITION CLOSED — {result}</b>\n"
            f"{'='*32}\n\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>Exit:</b> ${exit_price:,.2f}\n"
            f"<b>Order Type:</b> LIMIT ✅\n\n"
            f"<b>RESULT</b>\n"
            f"<b>P&L:</b> {'+'if is_profit else ''}{pnl_pct*100:.2f}%\n"
            f"<b>USD:</b> {'+'if is_profit else ''}${pnl:.4f}\n"
            f"<b>Reason:</b> {reason}\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # HARD STOP-LOSS
    # ---------------------------------------------------------------
    def send_hard_sl_alert(self, entry_price, sl_price):
        """Hard stop-loss placed notification."""
        self._send(
            f"<b>🛡️ HARD STOP-LOSS PLACED</b>\n\n"
            f"<b>Entry:</b> ${entry_price:,.2f}\n"
            f"<b>SL Price:</b> ${sl_price:,.2f}\n"
            f"<b>Distance:</b> -{config.HARD_STOP_LOSS_PCT*100}%\n"
            f"<b>Purpose:</b> Emergency liquidation protection\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # ORDER TIMEOUT
    # ---------------------------------------------------------------
    def send_order_timeout_alert(self, order_type="entry"):
        """Order timeout/cancel notification."""
        self._send(
            f"<b>⏰ ORDER TIMED OUT — CANCELLED</b>\n\n"
            f"<b>Type:</b> {order_type.upper()}\n"
            f"<b>Timeout:</b> Order execution failed\n"
            f"<b>Action:</b> Order cancelled, not chasing price\n\n"
            f"<i>{self._timestamp()}</i>"
        )

    # ---------------------------------------------------------------
    # BOT LOCKED (30% Drawdown)
    # ---------------------------------------------------------------
    def send_lock_alert(self, reason):
        """Bot locked due to 30% daily drawdown."""
        self._send(
            f"{'='*32}\n"
            f"<b>🔒 BOT PAUSED — 30% DRAWDOWN</b>\n"
            f"{'='*32}\n\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Duration:</b> {config.DAILY_LOCK_HOURS} hours\n\n"
            f"<i>Bot will auto-resume after cooldown</i>\n"
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
            f"{'='*32}\n"
            f"<b>⚠️ ERROR DETECTED</b>\n"
            f"{'='*32}\n\n"
            f"<b>Details:</b> {str(error)[:200]}\n\n"
            f"<i>Bot will attempt to recover...</i>\n"
            f"<i>{self._timestamp()}</i>"
        )
