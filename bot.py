"""
BTC Global Elite Scalper V6 — Main Trading Bot
Orchestrates data fetch, signal generation, safety checks, and execution.
"""

import logging
import time
from datetime import datetime, timezone

import pandas as pd

import config
from delta_client import DeltaClient
from indicators import calculate_all_indicators, get_current_signal
from risk_manager import RiskManager
from safety_filters import SafetyFilters
from order_executor import OrderExecutor
from alerts import AlertSystem
from database import Database

logger = logging.getLogger("TradingBot")

# Configure logging at startup
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(name)-15s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class TradingBot:
    """Core bot orchestrating data fetch, signal generation, safety checks, and execution."""

    def __init__(self):
        logger.info("Initializing BTC Global Elite Scalper V6...")
        self.client = DeltaClient()
        self.db = Database()
        self.alerts = AlertSystem()
        self.safety = SafetyFilters(self.client)
        self.risk = RiskManager(self.db)
        self.executor = OrderExecutor(self.client, self.db, self.alerts)

        # Cache product ID for BTC/USD
        self.product_id = self.client.get_product_id()
        if not self.product_id:
            logger.error("Failed to obtain product ID – bot may not execute trades")

        # Internal state
        self.last_candle_time = None
        logger.info("Bot initialized successfully (product_id=%s)", self.product_id)

        # Send professional startup notification via Telegram
        try:
            wallet = self.client.get_wallet_balance()
            balance = wallet.get("balance", 0)
            self.alerts.send_startup_alert(
                wallet_balance=balance,
                product_id=self.product_id,
            )
            logger.info("Startup Telegram alert sent")
        except Exception as e:
            logger.warning("Could not send startup alert: %s", e)

    def _fetch_and_prepare_candles(self):
        """Fetch OHLCV from Delta Exchange and return a DataFrame, or None on failure."""
        raw = self.client.get_candles(
            resolution=config.TIMEFRAME
        )
        if not raw:
            return None

        # Delta can return list of lists [[ts,o,h,l,c,v], ...] or list of dicts
        if isinstance(raw, list) and len(raw) > 0:
            if isinstance(raw[0], list):
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            elif isinstance(raw[0], dict):
                df = pd.DataFrame(raw)
                # Delta uses 'time' key instead of 'timestamp' — normalize
                if "time" in df.columns and "timestamp" not in df.columns:
                    df.rename(columns={"time": "timestamp"}, inplace=True)
            else:
                logger.error("Unknown candle format: %s", type(raw[0]))
                return None
        else:
            logger.warning("Empty or invalid candle data")
            return None

        # Ensure numeric
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Sort ascending by timestamp
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)

        return df

    def _manage_open_trade(self, open_trade, current_price):
        """
        Manage an existing open position:
        - Partial take profit
        - Breakeven SL
        - Timeout exit
        - Trailing SL after partial TP
        Returns True if position was closed (so main loop should skip entry logic).
        """
        side = open_trade["side"]
        entry_price = open_trade["entry_price"]

        # --- Partial TP ---
        tp_done, tp_msg = self.executor.check_partial_tp(
            self.product_id, entry_price, current_price, side,
            open_trade.get("partial_tp_done", False)
        )
        if tp_done:
            self.db.update_trade({"partial_tp_done": True})
            logger.info("Partial TP executed: %s", tp_msg)

        # --- Breakeven SL ---
        if not open_trade.get("breakeven_done", False):
            if self.safety.check_breakeven(entry_price, current_price, side):
                self.db.update_trade({"breakeven_done": True})
                self.alerts.send_breakeven_alert(side, entry_price)
                logger.info("SL moved to breakeven for %s @ $%.2f", side, entry_price)

        # --- Timeout exit ---
        entry_time_str = open_trade.get("entry_time")
        if entry_time_str:
            try:
                entry_time_dt = datetime.fromisoformat(str(entry_time_str))
                if entry_time_dt.tzinfo is None:
                    entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)
                if self.safety.check_timeout_exit(entry_time_dt):
                    self.executor.close_trade(self.product_id, reason="Timeout exit")
                    return True
            except Exception as e:
                logger.error("Failed to parse entry_time '%s': %s", entry_time_str, e)

        # --- Trailing SL (only after partial TP) ---
        if open_trade.get("partial_tp_done"):
            peak = open_trade.get("peak_price") or entry_price
            hit, new_peak, sl_price = self.executor.check_trailing_sl(
                side, entry_price, current_price, peak, trailing_active=True
            )
            if hit:
                self.executor.close_trade(self.product_id, reason="Trailing SL hit")
                return True
            if new_peak != peak:
                self.db.update_trade({"peak_price": new_peak})

        return False  # position still open, no exit triggered

    def run(self):
        """Main loop – polls candles, evaluates entry signals, and manages open trades."""
        logger.info("Bot started – mode: %s", config.MODE)

        while True:
            try:
                # -------- 1. Fetch candles --------
                df = self._fetch_and_prepare_candles()
                if df is None or len(df) < config.EMA_PERIOD:
                    logger.warning(
                        "Insufficient candle data (%s rows, need %s) – sleeping %ds",
                        len(df) if df is not None else 0,
                        config.EMA_PERIOD,
                        config.POLL_INTERVAL_SECONDS,
                    )
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue

                # -------- 2. Duplicate candle guard --------
                latest_ts = df["timestamp"].iloc[-1]
                candle_time = datetime.fromtimestamp(latest_ts, tz=timezone.utc)

                if self.last_candle_time and candle_time <= self.last_candle_time:
                    time.sleep(5)
                    continue

                self.last_candle_time = candle_time
                self.db.set_last_candle_time(candle_time.isoformat())

                # -------- 3. Calculate indicators (native – no pandas_ta) --------
                df = calculate_all_indicators(df)
                signal_info = get_current_signal(df)

                current_price = float(df["close"].iloc[-1])
                logger.info(
                    "Candle %s | Price=$%.2f | Signal=%s | STC=%.1f | EMA200=%.2f",
                    candle_time.strftime("%H:%M"),
                    current_price,
                    signal_info.get("signal", "None"),
                    signal_info.get("stc") or 0,
                    signal_info.get("ema200") or 0,
                )

                # -------- 4. Manage open trade (if any) --------
                open_trade = self.db.get_open_trade()
                if open_trade:
                    # Fetch fresh price from ticker
                    ticker = self.client.get_ticker()
                    if ticker:
                        live_price = float(ticker.get("close", current_price))
                    else:
                        live_price = current_price

                    closed = self._manage_open_trade(open_trade, live_price)
                    if closed:
                        continue  # restart loop after closing

                    # Position still open – sleep and re‑check
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue

                # -------- 5. Evaluate new entry --------
                signal = signal_info.get("signal")
                if signal in ("LONG", "SHORT"):
                    side = "buy" if signal == "LONG" else "sell"

                    # Safety checks
                    safe, results = self.safety.run_all_checks(self.product_id)
                    if not safe:
                        logger.warning("Safety filters blocked entry: %s", results)
                        self.db.log_event("SAFETY_BLOCK", str(results))
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    # Risk check: drawdown, position sizing, anti-martingale
                    wallet = self.client.get_wallet_balance()
                    balance = wallet.get("available_balance", 0)
                    if balance <= 0:
                        logger.error("No available balance – skipping entry")
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    approved, size, risk_msg = self.risk.pre_trade_check(balance, current_price)
                    if not approved:
                        logger.warning("Risk manager blocked entry: %s", risk_msg)
                        self.db.log_event("RISK_BLOCK", risk_msg)
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    # Execute
                    success, order, msg = self.executor.execute_entry(
                        self.product_id, side, size, current_price
                    )
                    if success:
                        logger.info("✅ Entered %s %s @ $%.2f: %s", side.upper(), size, current_price, msg)
                        self.db.log_event("ENTRY", msg, {"side": side, "size": size, "price": current_price})
                    else:
                        logger.error("❌ Entry failed: %s", msg)
                        self.db.log_event("ENTRY_FAIL", msg)

                # -------- 6. Sleep --------
                time.sleep(config.POLL_INTERVAL_SECONDS)

            except Exception as e:
                logger.exception("Unexpected error in main loop: %s", e)
                try:
                    self.alerts.send_error(str(e))
                except Exception:
                    pass
                time.sleep(10)
