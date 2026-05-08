"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Order Executor
ALL TRADES (entry + exit) are executed as MARKET ORDERS ONLY.
No limit orders allowed. 15-minute timeout on unfilled entries.
"""

import time
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger("OrderExecutor")


class OrderExecutor:
    """Handles market-order-only execution with timeout/cancel logic."""

    def __init__(self, delta_client, database, alerts):
        self.client = delta_client
        self.db = database
        self.alerts = alerts
        self._pending_entry_order_id = None
        self._pending_entry_time = None
        self._hard_sl_order_id = None

    # ---------------------------------------------------------------
    # CALCULATE MARKET PRICE
    # ---------------------------------------------------------------
    def _calc_limit_price(self, signal_close_price, side):
        """
        Limit price = signal close price with a 0.05% buffer.
        For BUY:  price + 0.05%  (slightly above to help fill)
        For SELL: price - 0.05%  (slightly below to help fill)
        """
        buffer = config.MARKET_BUFFER_PCT
        if side == "buy":
            return round(signal_close_price * (1 + buffer), 2)
        else:
            return round(signal_close_price * (1 - buffer), 2)

    # ---------------------------------------------------------------
    # ENTRY — MARKET ORDER ONLY
    # ---------------------------------------------------------------
    def execute_entry(self, product_id, size, signal_close_price):
        """
        Place a MARKET BUY order at the signal close price.
        Side is always 'buy' (LONG only strategy).

        Returns:
            (success: bool, order: dict, reason: str)
        """
        side = "buy"
        limit_price = self._calc_limit_price(signal_close_price, side)

        logger.info(
            f"🎯 Placing MARKET {side.upper()} entry: "
            f"size={size}, price=${limit_price} "
            f"(signal close=${signal_close_price})"
        )

        order = self.client.place_order(
            product_id=product_id,
            side=side,
            size=size,
            order_type="market_order",
            time_in_force="ioc",
            time_in_force="gtc",
        )

        if not order:
            return False, None, "Failed to place limit entry order"

        order_id = order.get("id")
        self._pending_entry_order_id = order_id
        self._pending_entry_time = time.time()

        logger.info(f"📋 Market entry order placed — ID: {order_id}, "
                     f"Price: ${limit_price}")

        # Now wait and poll for fill (up to 15 minutes / 900 seconds)
        filled, fill_data = self._wait_for_fill(
            order_id, product_id, timeout_seconds=15
        )

        if filled:
            fill_price = float(fill_data.get("average_fill_price", limit_price))
            logger.info(f"✅ Entry FILLED @ ${fill_price}")

            # Record trade in database
            trade_data = {
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "side": side,
                "entry_price": fill_price,
                "size": size,
                "status": "open",
                "order_id": order_id,
            }
            self.db.save_trade(trade_data)

            # Send entry alert
            self.alerts.send_entry_alert(
                side=side,
                price=fill_price,
                size=size,
            )

            # Place hard stop-loss at 8% below entry
            self._place_hard_stop_loss(product_id, fill_price, size)

            self._pending_entry_order_id = None
            self._pending_entry_time = None
            return True, fill_data, f"Filled @ ${fill_price}"
        else:
            # Not filled within timeout — cancel the order
            logger.warning(
                f"⏰ Entry order NOT filled within "
                f"{config.ORDER_TIMEOUT_MINUTES} minutes — CANCELLING"
            )
            self.client.cancel_order(order_id, product_id)
            self._pending_entry_order_id = None
            self._pending_entry_time = None
            return False, None, (
                f"Entry order expired (not filled in "
                f"{config.ORDER_TIMEOUT_MINUTES} min). Cancelled."
            )

    # ---------------------------------------------------------------
    # WAIT FOR FILL (polling)
    # ---------------------------------------------------------------
    def _wait_for_fill(self, order_id, product_id, timeout_seconds=900):
        """
        Poll order status until filled or timeout.
        Checks every 15 seconds.

        Returns:
            (filled: bool, order_data: dict or None)
        """
        start = time.time()
        check_interval = 15  # seconds

        while (time.time() - start) < timeout_seconds:
            updated = self.client.get_order(order_id)
            if updated:
                state = updated.get("state", "")
                if state in ("closed", "filled"):
                    return True, updated
                elif state in ("cancelled", "rejected"):
                    logger.warning(f"Order {order_id} was {state}")
                    return False, None
            time.sleep(check_interval)

        return False, None

    # ---------------------------------------------------------------
    # CHECK PENDING ENTRY TIMEOUT (called from main loop)
    # ---------------------------------------------------------------
    def has_pending_entry(self):
        """Check if there's a pending unfilled entry order."""
        return self._pending_entry_order_id is not None

    def check_entry_timeout(self, product_id):
        """
        If a pending entry order exceeds 15 min, cancel it.
        Returns True if order was cancelled.
        """
        if not self._pending_entry_order_id:
            return False

        elapsed = time.time() - (self._pending_entry_time or time.time())
        if elapsed >= config.ORDER_TIMEOUT_SECONDS:
            logger.warning(
                f"⏰ Pending entry timed out after {elapsed/60:.1f} min — cancelling"
            )
            self.client.cancel_order(
                self._pending_entry_order_id, product_id
            )
            self._pending_entry_order_id = None
            self._pending_entry_time = None
            return True
        return False

    # ---------------------------------------------------------------
    # HARD STOP-LOSS (Emergency — 8% below entry)
    # ---------------------------------------------------------------
    def _place_hard_stop_loss(self, product_id, entry_price, size):
        """
        Place a hard stop-loss at 8% below entry price.
        This is a stop-limit order on the exchange for liquidation protection.
        """
        sl_price = round(entry_price * (1 - config.HARD_STOP_LOSS_PCT), 2)
        logger.info(
            f"🛡️ Placing HARD Stop-Loss: "
            f"Entry=${entry_price}, SL=${sl_price} "
            f"(-{config.HARD_STOP_LOSS_PCT*100}%)"
        )

        # Place stop-limit sell order
        # Delta Exchange uses stop_limit_order or stop_market_order
        # We'll use a limit order slightly below the stop trigger
        sl_limit_price = round(sl_price * 0.998, 2)  # 0.2% below SL for fill assurance

        payload = {
            "product_id": product_id,
            "side": "sell",
            "size": size,
            "order_type": "limit_order",
            "limit_price": str(sl_limit_price),
            "stop_price": str(sl_price),
            "stop_order_type": "stop_loss_order",
            "time_in_force": "gtc",
        }

        try:
            from delta_client import DeltaClient
            import json
            path = "/v2/orders"
            url = f"{self.client.base_url}{path}"
            payload_str = json.dumps(payload, separators=(",", ":"))
            headers = self.client._auth_headers("POST", path, "", payload_str)

            resp = self.client.session.post(
                url, data=payload_str, headers=headers, timeout=(5, 30)
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") or data.get("result"):
                    result = data.get("result", data)
                    self._hard_sl_order_id = result.get("id")
                    logger.info(
                        f"✅ Hard SL placed — Order ID: {self._hard_sl_order_id}, "
                        f"Trigger: ${sl_price}, Limit: ${sl_limit_price}"
                    )
                    return
            logger.warning(f"Hard SL order may not have been placed: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to place hard SL: {e}")
            # Fallback: place regular limit order at SL price
            try:
                order = self.client.place_order(
                    product_id=product_id,
                    side="sell",
                    size=size,
                    order_type="limit_order",
                    limit_price=sl_price,
                )
                if order:
                    self._hard_sl_order_id = order.get("id")
                    logger.info(
                        f"✅ Hard SL fallback placed — ID: {self._hard_sl_order_id}"
                    )
            except Exception as e2:
                logger.error(f"Hard SL fallback also failed: {e2}")

    def cancel_hard_stop_loss(self, product_id):
        """Cancel the hard stop-loss order (when indicator exit triggers first)."""
        if self._hard_sl_order_id:
            logger.info(
                f"🔄 Cancelling hard SL order: {self._hard_sl_order_id}"
            )
            self.client.cancel_order(self._hard_sl_order_id, product_id)
            self._hard_sl_order_id = None

    # ---------------------------------------------------------------
    # EXIT — MARKET ORDER ONLY (indicator-based)
    # ---------------------------------------------------------------
    def execute_exit(self, product_id, current_price, reason="Indicator exit"):
        """
        Close the current LONG position via MARKET SELL order.
        Cancel the hard SL first, then place a limit sell.

        Returns:
            (success: bool, result: dict, reason: str)
        """
        pos = self.client.get_position(product_id)
        if not pos or pos["size"] == 0:
            return False, None, "No active position to close"

        entry_price = pos["entry_price"]
        side = pos["side"]
        size = abs(pos["size"])

        # Cancel hard SL first
        self.cancel_hard_stop_loss(product_id)

        # Place limit sell at current price with buffer
        limit_price = self._calc_limit_price(current_price, "sell")

        logger.info(
            f"🔒 Placing MARKET EXIT: SELL {size} @ ${limit_price} "
            f"(reason: {reason})"
        )

        order = self.client.place_order(
            product_id=product_id,
            side="sell",
            size=size,
            order_type="market_order",
            time_in_force="ioc",
        )

        if not order:
            # If limit fails, try with a more aggressive price
            aggressive_price = round(current_price * 0.999, 2)
            logger.warning(
                f"First exit limit failed, retrying at ${aggressive_price}"
            )
            order = self.client.place_order(
                product_id=product_id,
                side="sell",
                size=size,
                order_type="market_order",
                time_in_force="ioc",
            )
            if not order:
                return False, None, "Failed to place limit exit order"

        order_id = order.get("id")

        # Wait for exit fill (give 2 minutes, then retry at worse price)
        filled, fill_data = self._wait_for_fill(order_id, product_id, timeout_seconds=15)

        if filled:
            exit_price = float(fill_data.get("average_fill_price", limit_price))
        else:
            # Cancel and retry with more aggressive price
            self.client.cancel_order(order_id, product_id)
            aggressive_price = round(current_price * 0.997, 2)
            logger.warning(
                f"Exit not filled in 2 min, retrying at ${aggressive_price}"
            )
            order2 = self.client.place_order(
                product_id=product_id,
                side="sell",
                size=size,
                order_type="market_order",
                time_in_force="ioc",
            )
            if order2:
                filled2, fill_data2 = self._wait_for_fill(
                    order2.get("id"), product_id, timeout_seconds=15
                )
                if filled2:
                    exit_price = float(
                        fill_data2.get("average_fill_price", aggressive_price)
                    )
                else:
                    # Last resort: cancel and log failure
                    self.client.cancel_order(order2.get("id"), product_id)
                    return False, None, "Exit order not filled after retries"
            else:
                return False, None, "Failed to place retry exit order"

        # Calculate PnL
        pnl_pct = (exit_price - entry_price) / entry_price
        pnl_usd = pnl_pct * size  # Approximate

        # Update trade record
        self.db.update_trade({
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "exit_price": exit_price,
            "pnl": pnl_usd,
            "pnl_pct": pnl_pct,
            "status": "closed",
            "close_reason": reason,
        })

        # Send exit alert
        self.alerts.send_exit_alert(
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl_usd,
            pnl_pct=pnl_pct,
            reason=reason,
        )

        logger.info(
            f"🔒 Trade closed via MARKET: {side.upper()} "
            f"Entry: ${entry_price} → Exit: ${exit_price}, "
            f"P&L: {pnl_pct*100:.2f}%, Reason: {reason}"
        )

        return True, {
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "reason": reason,
        }, f"Exited @ ${exit_price}, P&L: {pnl_pct*100:.2f}%"

    # ---------------------------------------------------------------
    # SAMPLE TRADE (Verification — Step 6)
    # ---------------------------------------------------------------
    def execute_sample_trade(self, product_id):
        """
        Execute a live sample trade:
        1. Buy 1 contract (minimum) via limit order
        2. Immediately close via limit order
        3. Return confirmation log

        Returns:
            (success: bool, log: str)
        """
        logger.info("🧪 Executing SAMPLE TRADE for verification...")

        # Get current ticker price
        ticker = self.client.get_ticker()
        if not ticker:
            return False, "Failed to get ticker for sample trade"

        current_price = float(ticker.get("close", 0))
        if current_price <= 0:
            return False, "Invalid ticker price"

        # Minimum size = 1 contract
        size = 1
        buy_price = self._calc_limit_price(current_price, "buy")

        # Place buy
        logger.info(f"🧪 Sample BUY: {size} contract @ ${buy_price}")
        buy_order = self.client.place_order(
            product_id=product_id,
            side="buy",
            size=size,
            order_type="market_order",
            time_in_force="ioc",
        )

        if not buy_order:
            return False, "Sample BUY order failed"

        buy_id = buy_order.get("id")

        # Wait for fill (max 60 seconds for sample)
        filled, fill_data = self._wait_for_fill(buy_id, product_id, timeout_seconds=15)
        if not filled:
            self.client.cancel_order(buy_id, product_id)
            return False, "Sample BUY not filled in 60s — cancelled"

        fill_price = float(fill_data.get("average_fill_price", buy_price))
        logger.info(f"🧪 Sample BUY filled @ ${fill_price}")

        # Immediately close via limit sell
        sell_price = self._calc_limit_price(fill_price, "sell")
        logger.info(f"🧪 Sample SELL: {size} contract @ ${sell_price}")

        sell_order = self.client.place_order(
            product_id=product_id,
            side="sell",
            size=size,
            order_type="market_order",
            time_in_force="ioc",
        )

        if not sell_order:
            return False, "Sample SELL order failed"

        sell_id = sell_order.get("id")
        filled2, fill_data2 = self._wait_for_fill(sell_id, product_id, timeout_seconds=15)
        if not filled2:
            self.client.cancel_order(sell_id, product_id)
            return False, "Sample SELL not filled in 60s — cancelled"

        exit_price = float(fill_data2.get("average_fill_price", sell_price))
        logger.info(f"🧪 Sample SELL filled @ ${exit_price}")

        log = (
            f"✅ SAMPLE TRADE COMPLETE\n"
            f"  BUY: 1 contract @ ${fill_price} (Limit Order)\n"
            f"  SELL: 1 contract @ ${exit_price} (Limit Order)\n"
            f"  P&L: ${exit_price - fill_price:.4f}"
        )
        logger.info(log)
        return True, log
