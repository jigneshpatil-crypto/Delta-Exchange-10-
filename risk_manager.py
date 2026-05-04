"""
BTC Global Elite Scalper V6 — Risk Manager
Dynamic position sizing, daily drawdown lock, anti-martingale.
"""

import logging
from datetime import datetime, timedelta, timezone

import config

logger = logging.getLogger("RiskManager")


class RiskManager:
    """Capital protection and position sizing engine."""

    def __init__(self, database):
        self.db = database
        self._daily_start_balance = None
        self._last_trade_was_loss = False

    # ---------------------------------------------------------------
    # State Management
    # ---------------------------------------------------------------
    def load_state(self):
        """Load risk state from database."""
        state = self.db.get_bot_state()
        if state:
            self._daily_start_balance = state.get("daily_start_balance")
            self._last_trade_was_loss = state.get("last_trade_was_loss", False)
            logger.info(
                f"Risk state loaded — Daily start: ${self._daily_start_balance}, "
                f"Last trade loss: {self._last_trade_was_loss}"
            )

    def save_state(self):
        """Persist risk state to database."""
        self.db.update_bot_state({
            "daily_start_balance": self._daily_start_balance,
            "last_trade_was_loss": self._last_trade_was_loss,
        })

    # ---------------------------------------------------------------
    # Daily Reset
    # ---------------------------------------------------------------
    def check_daily_reset(self, current_balance):
        """Reset daily tracking at midnight UTC."""
        state = self.db.get_bot_state()
        last_reset = state.get("last_reset_date") if state else None
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if last_reset != today:
            self._daily_start_balance = current_balance
            self.db.update_bot_state({
                "daily_start_balance": current_balance,
                "last_reset_date": today,
                "is_locked": False,
                "lock_until": None,
            })
            logger.info(
                f"🔄 Daily reset — Starting balance: ${current_balance:.2f}"
            )
            return True
        return False

    # ---------------------------------------------------------------
    # Daily Drawdown Lock
    # ---------------------------------------------------------------
    def is_locked(self):
        """Check if bot is locked due to daily drawdown limit."""
        state = self.db.get_bot_state()
        if not state:
            return False

        if not state.get("is_locked", False):
            return False

        lock_until = state.get("lock_until")
        if lock_until:
            try:
                lock_dt = datetime.fromisoformat(lock_until)
                if lock_dt.tzinfo is None:
                    lock_dt = lock_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if now < lock_dt:
                    remaining = (lock_dt - now).total_seconds() / 3600
                    logger.warning(
                        f"🔒 Bot LOCKED — {remaining:.1f} hours remaining"
                    )
                    return True
                else:
                    # Lock expired, unlock
                    self.db.update_bot_state({
                        "is_locked": False,
                        "lock_until": None,
                    })
                    logger.info("🔓 Lock expired — Bot unlocked")
                    return False
            except (ValueError, TypeError):
                pass

        return state.get("is_locked", False)

    def check_drawdown(self, current_balance):
        """
        Check if daily drawdown limit has been hit.
        If 5% loss from daily start → lock bot for 24 hours.
        """
        if self._daily_start_balance is None or self._daily_start_balance <= 0:
            self._daily_start_balance = current_balance
            return False

        drawdown = (
            (self._daily_start_balance - current_balance) /
            self._daily_start_balance
        )

        if drawdown >= config.MAX_DAILY_DRAWDOWN:
            lock_until = (
                datetime.now(timezone.utc) +
                timedelta(hours=config.DAILY_LOCK_HOURS)
            )
            self.db.update_bot_state({
                "is_locked": True,
                "lock_until": lock_until.isoformat(),
            })
            reason = (
                f"🔒 DAILY DRAWDOWN LIMIT HIT! "
                f"Loss: {drawdown*100:.2f}% (limit: {config.MAX_DAILY_DRAWDOWN*100}%) "
                f"Start: ${self._daily_start_balance:.2f}, "
                f"Current: ${current_balance:.2f}. "
                f"Bot locked for {config.DAILY_LOCK_HOURS} hours."
            )
            logger.critical(reason)
            return True

        logger.debug(
            f"Drawdown: {drawdown*100:.2f}% "
            f"(limit: {config.MAX_DAILY_DRAWDOWN*100}%)"
        )
        return False

    # ---------------------------------------------------------------
    # Dynamic Position Sizing
    # ---------------------------------------------------------------
    def calculate_position_size(self, current_balance, current_price):
        """
        Calculate position size using 15% margin rule.
        With 10x leverage on a $10 account:
        - Margin = $10 * 0.15 = $1.50
        - Notional = $1.50 * 10x = $15.00
        - Size in BTC = $15 / price

        Returns:
            (size_contracts: int, margin_used: float, notional: float)
            size_contracts is the number of contracts (minimum 1)
        """
        if current_balance <= 0 or current_price <= 0:
            logger.error("Invalid balance or price for position sizing")
            return 0, 0, 0

        margin = current_balance * config.MARGIN_PERCENT
        notional = margin * config.LEVERAGE

        # Delta Exchange uses contract size (usually 1 contract = some USD value)
        # For BTCUSDT perpetual, 1 contract is typically $1 notional
        # So size = notional value in USD
        size_contracts = int(notional)

        # Ensure minimum size of 1
        if size_contracts < 1:
            size_contracts = 1
            margin = current_price / config.LEVERAGE
            notional = current_price

        logger.info(
            f"📊 Position sizing — Balance: ${current_balance:.2f}, "
            f"Margin (15%): ${margin:.2f}, "
            f"Leverage: {config.LEVERAGE}x, "
            f"Notional: ${notional:.2f}, "
            f"Size: {size_contracts} contracts"
        )

        return size_contracts, margin, notional

    # ---------------------------------------------------------------
    # Anti-Martingale
    # ---------------------------------------------------------------
    def record_trade_result(self, pnl):
        """
        Record whether last trade was a loss.
        Anti-martingale: never increase size after a loss.
        """
        self._last_trade_was_loss = pnl < 0
        self.save_state()

        if self._last_trade_was_loss:
            logger.info(
                "📉 Last trade was a LOSS — Anti-martingale active "
                "(no size increase)"
            )
        else:
            logger.info("📈 Last trade was a WIN")

    def apply_anti_martingale(self, base_size):
        """
        Apply anti-martingale rule: after a loss, use same or smaller size.
        After a win, use the calculated base size (no increase beyond base).
        """
        if self._last_trade_was_loss:
            # Keep same size — never increase after loss
            adjusted = base_size
            logger.info(
                f"Anti-martingale: Keeping size at {adjusted} "
                f"(same as base, no increase after loss)"
            )
        else:
            adjusted = base_size

        return max(1, adjusted)  # Minimum 1 contract

    # ---------------------------------------------------------------
    # Full Pre-Trade Risk Check
    # ---------------------------------------------------------------
    def pre_trade_check(self, current_balance, current_price):
        """
        Run all risk checks before placing a trade.

        Returns:
            (approved: bool, size: int, reason: str)
        """
        # Check if locked
        if self.is_locked():
            return False, 0, "Bot is locked due to daily drawdown limit"

        # Check daily trade count
        today_trades = self.db.get_today_trades()
        # Count closed trades + current open if any (though loop handles open)
        # Usually we count closed trades to see how many we've DONE
        closed_today = [t for t in today_trades if t.get("status") == "closed"]
        if len(closed_today) >= config.MAX_TRADES_PER_DAY:
            return False, 0, f"Daily trade limit ({config.MAX_TRADES_PER_DAY}) reached"

        # Check drawdown
        if self.check_drawdown(current_balance):
            return False, 0, "Daily drawdown limit just hit — locking bot"

        # Calculate position size
        size, margin, notional = self.calculate_position_size(
            current_balance, current_price
        )
        if size <= 0:
            return False, 0, "Position size too small"

        # Apply anti-martingale
        size = self.apply_anti_martingale(size)

        return True, size, f"Approved — Size: {size} contracts, Margin: ${margin:.2f}"
