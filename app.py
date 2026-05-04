"""
BTC Global Elite Scalper V6 — Flask Web Server
Professional dashboard + API endpoints for monitoring.
"""

import logging
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

import config
from bot import TradingBot

logger = logging.getLogger("App")

app = Flask(__name__)

# Initialize bot
bot = TradingBot()


# ---------------------------------------------------------------
# HTML Dashboard
# ---------------------------------------------------------------
@app.route("/")
@app.route("/dashboard")
def dashboard():
    """Serve the professional monitoring dashboard."""
    return render_template("dashboard.html")


# ---------------------------------------------------------------
# API Endpoints (JSON)
# ---------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok", "mode": config.MODE, "uptime": "running"})


@app.route("/api/status")
def api_status():
    """Full bot status for dashboard consumption."""
    try:
        # Bot state from DB
        state = bot.db.get_bot_state() or {}

        # Wallet balance
        wallet = bot.client.get_wallet_balance()

        # Current ticker
        ticker = bot.client.get_ticker() or {}

        # Open position
        position = bot.client.get_position(bot.product_id)

        # Recent trades
        recent_trades = bot.db.get_recent_trades(limit=20)

        # Today trades
        today_trades = bot.db.get_today_trades()
        today_pnl = sum(t.get("pnl", 0) or 0 for t in today_trades if t.get("status") == "closed")
        today_wins = sum(1 for t in today_trades if t.get("status") == "closed" and (t.get("pnl", 0) or 0) > 0)
        today_losses = sum(1 for t in today_trades if t.get("status") == "closed" and (t.get("pnl", 0) or 0) < 0)

        # Recent logs
        recent_logs = bot.db.get_recent_logs(limit=30)

        return jsonify({
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": config.MODE,
            "symbol": config.SYMBOL,
            "timeframe": config.TIMEFRAME,
            "leverage": config.LEVERAGE,
            "bot_state": {
                "is_locked": state.get("is_locked", False),
                "last_candle_time": str(state.get("last_candle_time", "")),
                "daily_start_balance": state.get("daily_start_balance", 0),
                "last_trade_was_loss": state.get("last_trade_was_loss", False),
            },
            "wallet": {
                "balance": wallet.get("balance", 0),
                "available": wallet.get("available_balance", 0),
                "asset": wallet.get("asset", "USD"),
            },
            "ticker": {
                "price": float(ticker.get("close", 0)),
                "mark_price": float(ticker.get("mark_price", 0)),
                "volume": float(ticker.get("volume", 0)),
            },
            "position": {
                "active": position is not None and position.get("size", 0) != 0,
                "side": position.get("side", "") if position else "",
                "size": abs(position.get("size", 0)) if position else 0,
                "entry_price": position.get("entry_price", 0) if position else 0,
                "pnl": position.get("unrealized_pnl", 0) if position else 0,
            } if position else {"active": False, "side": "", "size": 0, "entry_price": 0, "pnl": 0},
            "today": {
                "total_trades": len([t for t in today_trades if t.get("status") == "closed"]),
                "wins": today_wins,
                "losses": today_losses,
                "pnl": round(today_pnl, 4),
            },
            "recent_trades": [
                {
                    "id": t.get("id"),
                    "side": t.get("side", ""),
                    "entry_price": t.get("entry_price", 0),
                    "exit_price": t.get("exit_price", 0),
                    "pnl": t.get("pnl", 0),
                    "pnl_pct": t.get("pnl_pct", 0),
                    "status": t.get("status", ""),
                    "close_reason": t.get("close_reason", ""),
                    "entry_time": str(t.get("entry_time", "")),
                    "exit_time": str(t.get("exit_time", "")),
                }
                for t in recent_trades
            ],
            "recent_logs": [
                {
                    "timestamp": str(l.get("timestamp", "")),
                    "event_type": l.get("event_type", ""),
                    "message": l.get("message", ""),
                }
                for l in recent_logs
            ],
        })
    except Exception as e:
        logger.error(f"API status error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------
# Background Bot Thread
# ---------------------------------------------------------------
def start_background():
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    logger.info("Trading bot background thread started")


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=config.FLASK_PORT)
