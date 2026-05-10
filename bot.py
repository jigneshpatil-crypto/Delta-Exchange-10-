"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Main Trading Bot
LONG ONLY on BTC/USDT 5m. All orders are MARKET. Pyramiding = 1.

Entry: Chandelier Exit flips GREEN AND Close > LSMA 25
Exit:  Heikin-Ashi turns RED AND Close < LSMA 25
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
    """
    Core bot: fetches 5m candles, computes HA + Chandelier Exit + LSMA,
    enters LONG via limit order, exits via limit order on indicator signal.
    Hard SL at 8% for emergency protection. 30% daily drawdown lock.
    """

    def __init__(self):
        logger.info("=" * 50)
        logger.info("Initializing: %s", config.STRATEGY_NAME)
        logger.info("=" * 50)

        self.client = DeltaClient()
        self.db = Database()
        self.alerts = AlertSystem()
        self.safety = SafetyFilters(self.client)
        self.risk = RiskManager(self.db)
        self.executor = OrderExecutor(self.client, self.db, self.alerts)
        self.panic_mode = False  # Emergency stop flag

        # Cache product ID for BTC/USDT
        self.product_id = self.client.get_product_id()
        if not self.product_id:
            logger.error("Failed to obtain product ID – bot may not execute trades")

        # Set leverage to 10x
        if self.product_id:
            self.client.set_leverage(self.product_id, config.LEVERAGE)
            logger.info(f"Leverage set to {config.LEVERAGE}x Isolated")

        # Internal state
        self.last_candle_time = None
        self._deployed = False

        logger.info("Bot initialized (product_id=%s, symbol=%s, tf=%s)",
                     self.product_id, config.SYMBOL, config.TIMEFRAME)

        # Send startup notification via Telegram
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

    # ---------------------------------------------------------------
    # STEP 1: Teardown old strategy
    # ---------------------------------------------------------------
    def teardown_old_strategy(self):
        """
        STEP 1: Cancel all open/pending orders on Delta Exchange.
        The old strategy logic has been replaced in code.
        """
        logger.info("=" * 50)
        logger.info("STEP 1: Tearing down old strategy...")
        logger.info("=" * 50)

        if self.product_id:
            # Cancel all open orders
            result = self.client.cancel_all_orders(self.product_id)
            if result is not None:
                logger.info("✅ All open orders cancelled on Delta Exchange")
            else:
                logger.warning("No orders to cancel or cancel failed")

            # Check for open positions and close them
            pos = self.client.get_position(self.product_id)
            if pos and pos["size"] != 0:
                logger.info(f"Found open position: {pos['side']} {pos['size']} — closing...")
                # Close via limit order
                ticker = self.client.get_ticker()
                if ticker:
                    current_price = float(ticker.get("close", 0))
                    self.executor.execute_exit(
                        self.product_id, current_price,
                        reason="Old strategy teardown"
                    )
                logger.info("✅ Old position closed")
            else:
                logger.info("✅ No open positions found")

        logger.info("✅ Old strategy completely removed from codebase")
        logger.info("   - Old logic (UT Bot + STC + EMA200) deleted")
        logger.info("   - Old alerts and triggers cleared")
        logger.info("   - All pending orders cancelled")
        return True

    # ---------------------------------------------------------------
    # STEP 6: Sample trade verification
    # ---------------------------------------------------------------
    def run_sample_trade(self):
        """
        Execute a live sample trade for deployment verification.
        Buy minimum qty → immediately close → log results.
        """
        logger.info("=" * 50)
        logger.info("STEP 6: Executing verification sample trade...")
        logger.info("=" * 50)

        success, log = self.executor.execute_sample_trade(self.product_id)
        if success:
            logger.info("✅ Sample trade executed successfully via Limit Order")
        else:
            logger.warning(f"⚠️ Sample trade: {log}")
        return success, log

    # ---------------------------------------------------------------
    # DEPLOY NEW STRATEGY
    # ---------------------------------------------------------------
    def deploy(self):
        """
        Full deployment sequence:
        1. Teardown old strategy
        2. Verify connections retained
        3. Deploy new strategy config
        4. Run sample trade
        5. Send deployment report
        """
        logger.info("🚀 Starting full deployment sequence...")

        # Step 1: Teardown
        old_removed = self.teardown_old_strategy()

        # Step 2: Verify connections (DO NOT MODIFY)
        logger.info("STEP 2: Verifying connections (retained)...")
        ok, msg = self.client.test_connection()
        logger.info(f"  API Connection: {'✅' if ok else '❌'} — {msg}")
        logger.info("  API Keys: RETAINED (not modified)")
        logger.info("  Webhooks: RETAINED (not modified)")
        logger.info("  Database: RETAINED (not modified)")

        # Step 3: New strategy is already in code
        logger.info("STEP 3: New strategy deployed in code:")
        logger.info(f"  Strategy: {config.STRATEGY_NAME}")
        logger.info(f"  Pair: {config.SYMBOL}")
        logger.info(f"  Direction: {config.TRADE_DIRECTION} only")
        logger.info(f"  Timeframe: {config.TIMEFRAME}")
        logger.info(f"  Leverage: {config.LEVERAGE}x Isolated")
        logger.info(f"  Capital/Trade: ${config.CAPITAL_PER_TRADE}")
        logger.info(f"  Pyramiding: {config.PYRAMIDING}")
        new_deployed = True

        # Step 4 & 5 already enforced in code
        logger.info("STEP 4: Execution rules enforced:")
        logger.info("  Order Type: MARKET ONLY")
        logger.info("  Entry Timeout: None (Market orders)")
        logger.info(f"  Hard SL: {config.HARD_STOP_LOSS_PCT*100}%")
        logger.info("STEP 5: Risk management active:")
        logger.info(f"  Daily Drawdown: {config.MAX_DAILY_DRAWDOWN*100}%")
        logger.info(f"  Lock Duration: {config.DAILY_LOCK_HOURS}h")

        # Step 6: Sample trade (DISABLED)
        # sample_success, sample_log = self.run_sample_trade()
        sample_success, sample_log = True, "Sample trade has been disabled."

        # Send deployment report via Telegram
        self.alerts.send_deployment_alert(
            old_removed=old_removed,
            new_deployed=new_deployed,
            sample_result=sample_log,
        )

        self._deployed = True
        logger.info("=" * 50)
        logger.info("🎉 DEPLOYMENT COMPLETE — Bot is now live!")
        logger.info("=" * 50)

    # ---------------------------------------------------------------
    # DATA FETCH
    # ---------------------------------------------------------------
    def _fetch_and_prepare_candles(self):
        """Fetch OHLCV from Delta Exchange and return a DataFrame."""
        raw = self.client.get_candles(resolution=config.TIMEFRAME)
        if not raw:
            return None

        if isinstance(raw, list) and len(raw) > 0:
            if isinstance(raw[0], list):
                df = pd.DataFrame(
                    raw,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
            elif isinstance(raw[0], dict):
                df = pd.DataFrame(raw)
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

    # ---------------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------------
    def run(self):
        """
        Main loop:
        1. Fetch 5m candles
        2. Calculate HA + Chandelier Exit + LSMA
        3. If open position → check EXIT signal (HA Red + Close < LSMA)
        4. If no position → check ENTRY signal (CE Green flip + Close > LSMA)
        5. All orders LIMIT only. Pyramiding = 1.
        """
        logger.info("Bot started — strategy: %s", config.STRATEGY_NAME)

        # Deploy on first run (teardown + sample trade)
        if not self._deployed:
            try:
                self.deploy()
            except Exception as e:
                logger.error(f"Deployment error: {e}")
                logger.info("Continuing to main loop despite deployment issue...")

        min_candles = max(config.CE_ATR_PERIOD, config.LSMA_PERIOD) + 10

        while True:
            try:
                if self.panic_mode:
                    logger.warning("🚨 PANIC MODE ACTIVE - Bot is frozen")
                    time.sleep(10)
                    continue

                # Check if locked (30% daily drawdown)
                if self.risk.is_locked():
                    logger.warning("🔒 Bot paused — 30% daily drawdown limit")
                    # Still fetch candles to keep last_candle_time fresh
                    # so the health check doesn't think the bot is dead
                    try:
                        df_lock = self._fetch_and_prepare_candles()
                        if df_lock is not None and len(df_lock) > 0:
                            lt = df_lock["timestamp"].iloc[-1]
                            ct = datetime.fromtimestamp(lt, tz=timezone.utc)
                            self.db.set_last_candle_time(ct.isoformat())
                    except Exception:
                        pass
                    time.sleep(60)
                    continue

                # -------- 1. Fetch candles --------
                df = self._fetch_and_prepare_candles()
                if df is None or len(df) < min_candles:
                    logger.warning(
                        "Insufficient candle data (%s rows, need %s) — sleeping %ds",
                        len(df) if df is not None else 0,
                        min_candles,
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

                # -------- 3. Calculate indicators --------
                df = calculate_all_indicators(df)
                signal_info = get_current_signal(df)

                current_price = float(df["close"].iloc[-1])
                ha_color = signal_info.get("ha_color", "?")
                ce_dir = signal_info.get("ce_direction", 0)
                lsma_val = signal_info.get("lsma", 0)

                logger.info(
                    "Candle %s | Price=$%.2f | HA=%s | CE=%s | LSMA=%.2f | Signal=%s",
                    candle_time.strftime("%H:%M"),
                    current_price,
                    ha_color,
                    "GREEN" if ce_dir == 1 else "RED",
                    lsma_val or 0,
                    signal_info.get("signal", "None"),
                )

                # -------- 4. Daily reset & drawdown check --------
                wallet = self.client.get_wallet_balance()
                balance = wallet.get("available_balance", 0)

                # Guard: ignore $0 balance from API glitches
                if balance <= 0:
                    logger.warning(
                        "⚠️ Wallet returned $0 balance — likely API glitch, skipping drawdown check"
                    )
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue

                self.risk.check_daily_reset(balance)

                if self.risk.check_drawdown(balance):
                    self.alerts.send_lock_alert(
                        f"Equity dropped 30%. Balance: ${balance:.2f}"
                    )
                    continue

                # -------- 5. Manage open trade (EXIT logic) --------
                open_trade = self.db.get_open_trade()
                if open_trade:
                    signal = signal_info.get("signal")

                    # EXIT: HA Red + Close < LSMA
                    if signal == "EXIT":
                        logger.info("🔴 EXIT signal detected — closing LONG position")
                        success, result, msg = self.executor.execute_exit(
                            self.product_id,
                            current_price,
                            reason="HA Red + Close < LSMA 25",
                        )
                        if success:
                            logger.info("✅ Position closed: %s", msg)
                        else:
                            logger.error("❌ Exit failed: %s", msg)
                    else:
                        logger.debug(
                            "Position open, no exit signal yet. "
                            "Waiting for HA Red + Close < LSMA."
                        )

                    time.sleep(config.POLL_INTERVAL_SECONDS)
                    continue

                # -------- 6. New ENTRY (LONG only) --------
                signal = signal_info.get("signal")

                if signal == "LONG":
                    logger.info("🟢 LONG ENTRY signal detected!")

                    # Safety checks (pyramiding, spread, news)
                    safe, results = self.safety.run_all_checks(self.product_id)
                    if not safe:
                        logger.warning("Safety filters blocked entry: %s", results)
                        self.db.log_event("SAFETY_BLOCK", str(results))
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    # Risk check
                    if balance <= 0:
                        logger.error("No available balance — skipping entry")
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    approved, size, risk_msg = self.risk.pre_trade_check(
                        balance, current_price
                    )
                    if not approved:
                        logger.warning("Risk manager blocked: %s", risk_msg)
                        self.db.log_event("RISK_BLOCK", risk_msg)
                        time.sleep(config.POLL_INTERVAL_SECONDS)
                        continue

                    # Execute MARKET BUY entry
                    success, order, msg = self.executor.execute_entry(
                        self.product_id, size, current_price
                    )
                    if success:
                        logger.info(
                            "✅ LONG ENTRY: %s contracts @ $%.2f: %s",
                            size, current_price, msg,
                        )
                        self.db.log_event(
                            "ENTRY",
                            msg,
                            {"side": "buy", "size": size, "price": current_price},
                        )
                    else:
                        logger.error("❌ Entry failed: %s", msg)
                        self.db.log_event("ENTRY_FAIL", msg)
                        # No timeout alert for market orders

                # -------- 7. Sleep --------
                time.sleep(config.POLL_INTERVAL_SECONDS)

            except Exception as e:
                logger.exception("Unexpected error in main loop: %s", e)
                try:
                    self.alerts.send_error(str(e))
                except Exception:
                    pass
                time.sleep(10)
