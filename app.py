"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Flask Web Server
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
    return jsonify({
        "status": "ok",
        "mode": config.MODE,
        "strategy": config.STRATEGY_NAME,
        "uptime": "running",
    })


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
        today_pnl = sum(
            t.get("pnl", 0) or 0
            for t in today_trades
            if t.get("status") == "closed"
        )
        today_wins = sum(
            1 for t in today_trades
            if t.get("status") == "closed" and (t.get("pnl", 0) or 0) > 0
        )
        today_losses = sum(
            1 for t in today_trades
            if t.get("status") == "closed" and (t.get("pnl", 0) or 0) < 0
        )

        # Recent logs
        recent_logs = bot.db.get_recent_logs(limit=30)

        return jsonify({
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": config.MODE,
            "strategy": config.STRATEGY_NAME,
            "symbol": config.SYMBOL,
            "timeframe": config.TIMEFRAME,
            "leverage": config.LEVERAGE,
            "direction": config.TRADE_DIRECTION,
            "panic_mode": bot.panic_mode,
            "bot_state": {
                "is_locked": state.get("is_locked", False),
                "last_candle_time": str(state.get("last_candle_time", "")),
                "daily_start_balance": state.get("daily_start_balance", 0),
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
            } if position else {
                "active": False, "side": "", "size": 0,
                "entry_price": 0, "pnl": 0,
            },
            "risk": {
                "hard_sl_pct": config.HARD_STOP_LOSS_PCT * 100,
                "daily_drawdown_pct": config.MAX_DAILY_DRAWDOWN * 100,
                "capital_per_trade": config.CAPITAL_PER_TRADE,
                "pyramiding": config.PYRAMIDING,
                "order_timeout_min": config.ORDER_TIMEOUT_MINUTES,
            },
            "today": {
                "total_trades": len([
                    t for t in today_trades if t.get("status") == "closed"
                ]),
                "wins": today_wins,
                "losses": today_losses,
                "pnl": round(today_pnl, 4),
            },
            "recent_trades": [
                {
                    "id": t.get("id"),
                    "side": t.get("side", "").upper(),
                    "entry_price": t.get("entry_price", 0),
                    "exit_price": t.get("exit_price", 0),
                    "pnl": t.get("pnl", 0),
                    "pnl_pct": t.get("pnl_pct", 0),
                    "status": t.get("status", "").upper(),
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


@app.route("/api/diagnostic")
def api_diagnostic():
    """Check environment health (without exposing secrets)."""
    return jsonify({
        "mode": config.MODE,
        "strategy": config.STRATEGY_NAME,
        "symbol": config.SYMBOL,
        "timeframe": config.TIMEFRAME,
        "direction": config.TRADE_DIRECTION,
        "api_key_set": len(config.DELTA_API_KEY) > 10,
        "api_secret_set": len(config.DELTA_API_SECRET) > 10,
        "db_connected": bot.db.test_connection(),
        "product_id": bot.product_id,
        "base_url": config.DELTA_BASE_URL,
    })


@app.route("/api/panic", methods=["POST"])
def api_panic():
    """Toggle panic mode (Emergency Stop)."""
    bot.panic_mode = not bot.panic_mode
    action = "ACTIVATED" if bot.panic_mode else "DEACTIVATED"
    bot.db.log_event("PANIC_TOGGLE", f"Panic mode {action} via dashboard")
    return jsonify({
        "ok": True,
        "panic_mode": bot.panic_mode,
        "message": f"Panic mode {action}",
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Force re-sync of wallet and product state."""
    try:
        bot.product_id = bot.client.get_product_id()
        wallet = bot.client.get_wallet_balance()
        bot.db.log_event(
            "MANUAL_REFRESH",
            "System state re-synchronized via dashboard",
        )
        return jsonify({
            "ok": True,
            "product_id": bot.product_id,
            "wallet": wallet,
            "message": "System synchronized successfully",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------
# Background Bot Thread
# ---------------------------------------------------------------
def start_background():
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    logger.info("Trading bot background thread started")

    # SCHEDULED 5-MINUTE TEST FOR VERIFICATION (Test 2) - DISABLED
    # def delayed_test_alert():
    #     try:
    #         logger.info("Executing 5-minute delayed test (Test 2) to verify automation...")
    #         bot.db.log_event("AUTOMATION_TEST_2", "Sending 5-minute delayed test message (Test 2).")
    #         bot.alerts.send_status(
    #             "🤖 <b>AUTOMATION TEST #2 SUCCESSFUL!</b> 🤖\n\n"
    #             "Aapne dobara test karne bola tha, aur ye raha result! Ye message server restart hone ke theek 5 minute baad aaya hai.\n\n"
    #             "Aapka bot <b>Render Cloud</b> par perfectly chal raha hai. Aap abhi laptop band kar diye honge aur fir bhi ye background me run kar raha hai!\n\n"
    #             "System 100% cloud par independent hai. ✅"
    #         )
    #     except Exception as e:
    #         logger.error(f"Failed to execute delayed test: {e}")

    # test_timer = threading.Timer(300.0, delayed_test_alert)
    # test_timer.daemon = True
    # test_timer.start()
    # logger.info("Scheduled 5-minute delayed test alert (Test 2).")

# Start background thread automatically when app is imported by Gunicorn
start_background()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT)
