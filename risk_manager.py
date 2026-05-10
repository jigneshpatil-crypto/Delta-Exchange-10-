"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Risk Manager
$10 capital per trade, 30% daily drawdown lock, position sizing for BTC/USDT.
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

    # ---------------------------------------------------------------
    # State Management
    # ---------------------------------------------------------------
    def load_state(self):
        """Load risk state from database."""
        state = self.db.get_bot_state()
        if state:
            self._daily_start_balance = state.get("daily_start_balance")
            logger.info(
                f"Risk state loaded — Daily start: ${self._daily_start_balance}"
            )

    def save_state(self):
        """Persist risk state to database."""
        self.db.update_bot_state({
            "daily_start_balance": self._daily_start_balance,
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
    # Daily Drawdown Lock (30%)
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
                        f"🔒 Bot LOCKED — {remaining:.1f} hours remaining "
                        f"(30% daily drawdown hit)"
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
        Check if daily drawdown limit (30%) has been hit.
        If equity drops by 30% (e.g., $3 loss on $10 account) → lock for 24h.
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
                f"Loss: {drawdown*100:.1f}% (limit: {config.MAX_DAILY_DRAWDOWN*100}%) "
                f"Start: ${self._daily_start_balance:.2f}, "
                f"Current: ${current_balance:.2f}. "
                f"Bot paused for {config.DAILY_LOCK_HOURS} hours."
            )
            logger.critical(reason)
            return True

        logger.debug(
            f"Drawdown: {drawdown*100:.1f}% "
            f"(limit: {config.MAX_DAILY_DRAWDOWN*100}%)"
        )
        return False

    # ---------------------------------------------------------------
    # Position Sizing ($10 capital per trade)
    # ---------------------------------------------------------------
    def calculate_position_size(self, current_balance, current_price):
        """
        Calculate position size.
        Capital per trade: $10 (or 100% of available balance if < $10).
        Leverage: 50x Isolated.

        Delta Exchange India BTCUSD:
            1 contract = 0.001 BTC
            Contract value in USD = current_price * 0.001

        Notional = min($10, balance) * leverage
        Size in contracts = Notional / (current_price * 0.001)

        Example at BTC=$80,000, $10 capital, 50x leverage:
            Notional = $10 * 50 = $500
            Contract value = $80,000 * 0.001 = $80
            Size = $500 / $80 = 6 contracts

        Returns:
            (size_contracts: int, margin_used: float, notional: float)
        """
        if current_balance <= 0 or current_price <= 0:
            logger.error("Invalid balance or price for position sizing")
            return 0, 0, 0

        # Use $10 or entire balance if less
        capital = min(config.CAPITAL_PER_TRADE, current_balance)
        notional = capital * config.LEVERAGE  # $10 * 50x = $500

        # Delta Exchange BTCUSD: 1 contract = 0.001 BTC
        contract_value_usd = current_price * 0.001
        size_contracts = int(notional / contract_value_usd)

        # Ensure minimum size of 1
        if size_contracts < 1:
            size_contracts = 1

        margin_used = capital

        logger.info(
            f"📊 Position sizing — Balance: ${current_balance:.2f}, "
            f"Capital: ${capital:.2f}, "
            f"Leverage: {config.LEVERAGE}x, "
            f"Notional: ${notional:.2f}, "
            f"Contract value: ${contract_value_usd:.2f}, "
            f"Size: {size_contracts} contracts"
        )

        return size_contracts, margin_used, notional

    # ---------------------------------------------------------------
    # Full Pre-Trade Risk Check
    # ---------------------------------------------------------------
    def pre_trade_check(self, current_balance, current_price):
        """
        Run all risk checks before placing a trade.

        Returns:
            (approved: bool, size: int, reason: str)
        """
        # Check if locked (30% daily drawdown)
        if self.is_locked():
            return False, 0, "Bot is locked — 30% daily drawdown limit hit"

        # Check drawdown
        if self.check_drawdown(current_balance):
            return False, 0, "Daily drawdown limit just hit — pausing bot for 24h"

        # Calculate position size
        size, margin, notional = self.calculate_position_size(
            current_balance, current_price
        )
        if size <= 0:
            return False, 0, "Position size too small"

        return True, size, f"Approved — Size: {size} contracts, Margin: ${margin:.2f}"
