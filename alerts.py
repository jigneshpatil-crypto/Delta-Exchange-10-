"""
BTC Global Elite Scalper V6 — Telegram Alert System
Sends trade notifications via Telegram Bot API (free).
"""
import logging, requests, config

logger = logging.getLogger("Alerts")

class AlertSystem:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.warning("Telegram alerts DISABLED — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    def _send(self, text):
        if not self.enabled:
            logger.info(f"[ALERT] {text}")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": self.chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True
            }, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def send_entry_alert(self, side, price, size, attempt=1):
        emoji = "🟢" if side == "buy" else "🔴"
        self._send(
            f"{emoji} <b>NEW TRADE ENTRY</b>\n"
            f"Side: <b>{side.upper()}</b>\n"
            f"Price: <b>${price:.2f}</b>\n"
            f"Size: <b>{size} contracts</b>\n"
            f"Fill attempt: {attempt}/{config.CHASE_MAX_ATTEMPTS}\n"
            f"Mode: {config.MODE.upper()}"
        )

    def send_exit_alert(self, side, entry_price, exit_price, pnl_pct, reason):
        emoji = "💰" if pnl_pct >= 0 else "💸"
        self._send(
            f"{emoji} <b>TRADE CLOSED</b>\n"
            f"Side: <b>{side.upper()}</b>\n"
            f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}\n"
            f"P&L: <b>{pnl_pct*100:.2f}%</b>\n"
            f"Reason: {reason}"
        )

    def send_partial_tp_alert(self, side, entry_price, exit_price, profit_pct):
        self._send(
            f"💰 <b>PARTIAL TP (50%)</b>\n"
            f"Side: {side.upper()}\n"
            f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}\n"
            f"Profit: {profit_pct*100:.2f}%\n"
            f"Remaining 50% on trailing SL"
        )

    def send_breakeven_alert(self, side, entry_price):
        self._send(f"🛡️ <b>SL → BREAKEVEN</b>\nSide: {side.upper()}\nSL moved to entry: ${entry_price:.2f}")

    def send_lock_alert(self, reason):
        self._send(f"🔒 <b>BOT LOCKED</b>\n{reason}")

    def send_sl_hit_alert(self, side, entry_price, sl_price, pnl_pct):
        self._send(
            f"🛑 <b>STOP LOSS HIT</b>\n"
            f"Side: {side.upper()}\nEntry: ${entry_price:.2f}\n"
            f"SL: ${sl_price:.2f}\nP&L: {pnl_pct*100:.2f}%"
        )

    def send_status(self, message):
        self._send(f"ℹ️ {message}")

    def send_error(self, error):
        self._send(f"⚠️ <b>ERROR</b>\n{error}")
