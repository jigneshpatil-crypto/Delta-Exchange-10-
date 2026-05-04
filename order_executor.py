"""
BTC Global Elite Scalper V6 — Order Executor
Smart limit order chase with partial take profit and trailing stop loss.
"""

import time
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger("OrderExecutor")


class OrderExecutor:
    """Handles intelligent order placement and position management."""

    def __init__(self, delta_client, database, alerts):
        self.client = delta_client
        self.db = database
        self.alerts = alerts

    # ---------------------------------------------------------------
    # LIMIT ORDER WITH CHASE
    # ---------------------------------------------------------------
    def execute_entry(self, product_id, side, size, current_price):
        """
        Place a limit order with chase logic.
        1. Place limit at best bid/ask
        2. Wait 5 seconds
        3. If not filled → cancel, re-place 1 tick better
        4. Repeat up to 3 times
        5. If still unfilled → give up

        Returns:
            (success: bool, order: dict, reason: str)
        """
        logger.info(
            f"🎯 Executing entry: {side.upper()} {size} contracts "
            f"@ ~${current_price}"
        )

        # Get best bid/ask for initial limit price
        orderbook = self.client.get_orderbook()
        if not orderbook:
            return False, None, "Failed to fetch orderbook for limit pricing"

        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])

        if not bids or not asks:
            return False, None, "Empty orderbook"

        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])

        # Determine limit price based on side
        if side == "buy":
            # Place at best bid (passive) then chase up
            limit_price = best_bid
        else:
            # Place at best ask (passive) then chase down
            limit_price = best_ask

        # Get tick size for price adjustments
        product_info = self.client.get_product_info()
        tick_size = 0.5  # Default for BTC
        if product_info:
            tick_size = float(product_info.get("tick_size", 0.5))

        # Chase loop
        for attempt in range(1, config.CHASE_MAX_ATTEMPTS + 1):
            logger.info(
                f"Chase attempt {attempt}/{config.CHASE_MAX_ATTEMPTS}: "
                f"{side.upper()} {size} @ ${limit_price}"
            )

            # Place limit order
            order = self.client.place_order(
                product_id=product_id,
                side=side,
                size=size,
                order_type="limit_order",
                limit_price=limit_price,
            )

            if not order:
                return False, None, f"Failed to place order on attempt {attempt}"

            order_id = order.get("id")

            # Wait for fill
            time.sleep(config.CHASE_WAIT_SECONDS)

            # Check if filled
            updated_order = self.client.get_order(order_id)
            if updated_order:
                state = updated_order.get("state", "")
                if state in ("closed", "filled"):
                    fill_price = float(
                        updated_order.get("average_fill_price", limit_price)
                    )
                    logger.info(
                        f"✅ Order FILLED on attempt {attempt}! "
                        f"Price: ${fill_price}"
                    )

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

                    # Send Telegram alert
                    self.alerts.send_entry_alert(
                        side=side,
                        price=fill_price,
                        size=size,
                        attempt=attempt,
                    )

                    return True, updated_order, f"Filled @ ${fill_price}"

            # Not filled — cancel and chase
            if attempt < config.CHASE_MAX_ATTEMPTS:
                self.client.cancel_order(order_id, product_id)
                logger.info(
                    f"Order not filled, cancelling and chasing "
                    f"(+{config.CHASE_TICK_OFFSET} tick)"
                )

                # Move price aggressively
                if side == "buy":
                    limit_price += tick_size * config.CHASE_TICK_OFFSET
                    limit_price = min(limit_price, best_ask)  # Don't exceed ask
                else:
                    limit_price -= tick_size * config.CHASE_TICK_OFFSET
                    limit_price = max(limit_price, best_bid)  # Don't go below bid
            else:
                # Final attempt failed — cancel and give up
                self.client.cancel_order(order_id, product_id)
                reason = (
                    f"Order chase failed after {config.CHASE_MAX_ATTEMPTS} attempts"
                )
                logger.warning(reason)
                return False, None, reason

        return False, None, "Order chase exhausted"

    # ---------------------------------------------------------------
    # PARTIAL TAKE PROFIT
    # ---------------------------------------------------------------
    def check_partial_tp(self, product_id, entry_price, current_price, side,
                         partial_done=False):
        """
        Check and execute partial take profit.
        At 1% profit → close 50% position.

        Returns:
            (took_partial: bool, reason: str)
        """
        if partial_done:
            return False, "Partial TP already executed"

        if side == "long":
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        if profit_pct >= config.PARTIAL_TP_PCT:
            logger.info(
                f"💰 Partial TP triggered! Profit: {profit_pct*100:.2f}% >= "
                f"{config.PARTIAL_TP_PCT*100}% — Closing 50% position"
            )

            result = self.client.close_partial_position(
                product_id, fraction=config.PARTIAL_TP_SIZE_RATIO
            )

            if result:
                self.alerts.send_partial_tp_alert(
                    side=side,
                    entry_price=entry_price,
                    exit_price=current_price,
                    profit_pct=profit_pct,
                )
                return True, f"Partial TP: 50% closed @ ${current_price}"
            else:
                return False, "Partial TP order failed"

        return False, f"Profit {profit_pct*100:.2f}% < {config.PARTIAL_TP_PCT*100}%"

    # ---------------------------------------------------------------
    # TRAILING STOP LOSS (for remaining position after partial TP)
    # ---------------------------------------------------------------
    def calculate_trailing_sl(self, side, peak_price, current_price):
        """
        Calculate trailing stop loss price.
        Trail by 0.5% from the peak profit.

        Returns:
            trailing_sl_price: float
        """
        offset = config.TRAILING_SL_OFFSET_PCT

        if side == "long":
            # SL trails below peak
            return peak_price * (1 - offset)
        else:
            # SL trails above peak (for shorts, peak = lowest)
            return peak_price * (1 + offset)

    def check_trailing_sl(self, side, entry_price, current_price,
                          peak_price, trailing_active=False):
        """
        Check if trailing stop has been hit.

        Returns:
            (hit: bool, updated_peak: float, sl_price: float)
        """
        if not trailing_active:
            # Activate trailing SL after partial TP
            return False, peak_price, 0

        # Update peak
        if side == "long":
            peak_price = max(peak_price, current_price)
        else:
            peak_price = min(peak_price, current_price)

        sl_price = self.calculate_trailing_sl(side, peak_price, current_price)

        # Check if SL hit
        if side == "long" and current_price <= sl_price:
            logger.warning(
                f"🛑 Trailing SL HIT! Price ${current_price} <= SL ${sl_price}"
            )
            return True, peak_price, sl_price
        elif side == "short" and current_price >= sl_price:
            logger.warning(
                f"🛑 Trailing SL HIT! Price ${current_price} >= SL ${sl_price}"
            )
            return True, peak_price, sl_price

        return False, peak_price, sl_price

    # ---------------------------------------------------------------
    # CLOSE POSITION (Full Exit)
    # ---------------------------------------------------------------
    def close_trade(self, product_id, reason="Manual close"):
        """
        Close entire position and record the trade.
        """
        pos = self.client.get_position(product_id)
        if not pos or pos["size"] == 0:
            return False, "No active position to close"

        entry_price = pos["entry_price"]
        side = pos["side"]

        # Close via market order
        result = self.client.close_position(product_id)
        if not result:
            return False, "Failed to close position"

        # Get exit price from the closing order
        exit_price = float(result.get("average_fill_price", 0))
        if exit_price == 0:
            # Estimate from current ticker
            ticker = self.client.get_ticker()
            if ticker:
                exit_price = float(ticker.get("close", 0))

        # Calculate PnL
        if side == "long":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price

        pnl_usd = pnl_pct * abs(pos["size"])

        # Update trade record
        self.db.update_trade({
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "exit_price": exit_price,
            "pnl": pnl_usd,
            "pnl_pct": pnl_pct,
            "status": "closed",
            "close_reason": reason,
        })

        # Send alert
        self.alerts.send_exit_alert(
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            reason=reason,
        )

        logger.info(
            f"🔒 Trade closed: {side.upper()} "
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
        }
