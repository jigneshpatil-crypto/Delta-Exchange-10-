"""
BTC Global Elite Scalper V6 — Safety Filters
Advanced loss prevention layer: News Filter, Spread Guard,
Time-Out Exit, Max 1 Trade, Breakeven Logic.
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests

import config

logger = logging.getLogger("SafetyFilters")


class SafetyFilters:
    """All safety checks that must pass before entering a trade."""

    def __init__(self, delta_client):
        self.client = delta_client
        self._news_cache = []
        self._news_cache_time = 0
        self._NEWS_CACHE_TTL = 3600  # Refresh news every 1 hour

    # ---------------------------------------------------------------
    # 1. NEWS FILTER (Auto-Pause)
    # ---------------------------------------------------------------
    def _fetch_economic_calendar(self):
        """Fetch high-impact news events from Finnhub (free tier)."""
        now = time.time()
        if now - self._news_cache_time < self._NEWS_CACHE_TTL and self._news_cache:
            return self._news_cache

        if not config.FINNHUB_API_KEY:
            logger.warning("Finnhub API key not set — news filter disabled")
            return []

        try:
            today = datetime.now(timezone.utc)
            from_date = today.strftime("%Y-%m-%d")
            to_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

            url = "https://finnhub.io/api/v1/calendar/economic"
            params = {
                "from": from_date,
                "to": to_date,
                "token": config.FINNHUB_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            events = data.get("economicCalendar", [])

            # Filter for high-impact USD events
            high_impact = []
            for event in events:
                impact = str(event.get("impact", "")).lower()
                country = event.get("country", "")
                event_name = event.get("event", "")

                # Only USD high-impact events
                if country != "US":
                    continue
                if impact not in ("high", "3"):
                    # Also check by event name keywords
                    is_high = any(
                        kw.lower() in event_name.lower()
                        for kw in config.HIGH_IMPACT_EVENTS
                    )
                    if not is_high:
                        continue

                high_impact.append(event)

            self._news_cache = high_impact
            self._news_cache_time = now
            logger.info(
                f"Fetched {len(high_impact)} high-impact news events for today"
            )
            return high_impact

        except Exception as e:
            logger.error(f"Failed to fetch economic calendar: {e}")
            return self._news_cache  # Return stale cache on error

    def check_news_filter(self):
        """
        Returns (is_safe, reason).
        Blocks trading 30 min before and after high-impact news.
        """
        events = self._fetch_economic_calendar()
        if not events:
            return True, "No high-impact news events"

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=config.NEWS_BUFFER_MINUTES)

        for event in events:
            # Parse event time
            event_time_str = event.get("time", "")
            event_date = event.get("date", "")

            if not event_time_str or not event_date:
                continue

            try:
                event_dt = datetime.strptime(
                    f"{event_date} {event_time_str}", "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    event_dt = datetime.strptime(
                        f"{event_date} {event_time_str}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

            # Check if we're within the buffer window
            if (event_dt - buffer) <= now <= (event_dt + buffer):
                event_name = event.get("event", "Unknown")
                reason = (
                    f"Skipping trade due to High News Volatility: "
                    f"'{event_name}' at {event_dt.strftime('%H:%M UTC')}"
                )
                logger.warning(reason)
                return False, reason

        return True, "News filter passed"

    # ---------------------------------------------------------------
    # 2. SPREAD GUARD
    # ---------------------------------------------------------------
    def check_spread(self):
        """
        Returns (is_safe, spread_pct, reason).
        Blocks if bid-ask spread > 0.05%.
        """
        orderbook = self.client.get_orderbook()
        if not orderbook:
            return False, 0, "Failed to fetch orderbook"

        try:
            # Orderbook format: {"buy": [{"price": ..., "size": ...}], "sell": [...]}
            bids = orderbook.get("buy", [])
            asks = orderbook.get("sell", [])

            if not bids or not asks:
                return False, 0, "Empty orderbook — no liquidity"

            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0

            if best_bid <= 0 or best_ask <= 0:
                return False, 0, "Invalid orderbook prices"

            mid_price = (best_bid + best_ask) / 2
            spread = (best_ask - best_bid) / mid_price

            if spread > config.SPREAD_THRESHOLD_PCT:
                reason = (
                    f"Spread too high: {spread*100:.4f}% "
                    f"(max: {config.SPREAD_THRESHOLD_PCT*100:.2f}%) "
                    f"— Bid: {best_bid}, Ask: {best_ask}"
                )
                logger.warning(reason)
                return False, spread, reason

            return (
                True,
                spread,
                f"Spread OK: {spread*100:.4f}% — Bid: {best_bid}, Ask: {best_ask}",
            )

        except (KeyError, IndexError, ValueError) as e:
            return False, 0, f"Error parsing orderbook: {e}"

    # ---------------------------------------------------------------
    # 3. MAX 1 ACTIVE TRADE
    # ---------------------------------------------------------------
    def check_max_trades(self, product_id=None):
        """
        Returns (is_safe, reason).
        Blocks if there's already an active position.
        """
        pos = self.client.get_position(product_id)
        if pos and pos["size"] != 0:
            reason = (
                f"Active trade exists — {pos['side'].upper()} "
                f"size={abs(pos['size'])} @ {pos['entry_price']}, "
                f"P&L: {pos['unrealized_pnl']}"
            )
            logger.info(reason)
            return False, reason

        return True, "No active trades"

    # ---------------------------------------------------------------
    # 4. TIME-OUT EXIT CHECK
    # ---------------------------------------------------------------
    def check_timeout_exit(self, trade_entry_time):
        """
        Returns True if trade has exceeded timeout limit.
        trade_entry_time: datetime object (UTC)
        """
        if not trade_entry_time:
            return False

        now = datetime.now(timezone.utc)
        elapsed = (now - trade_entry_time).total_seconds() / 60  # minutes

        if elapsed >= config.TIMEOUT_MINUTES:
            logger.warning(
                f"Trade timeout! Open for {elapsed:.1f} min "
                f"(limit: {config.TIMEOUT_MINUTES} min). Closing position."
            )
            return True

        return False

    # ---------------------------------------------------------------
    # 5. BREAKEVEN LOGIC
    # ---------------------------------------------------------------
    def check_breakeven(self, entry_price, current_price, side):
        """
        Returns True if breakeven condition is met (0.5% profit reached).
        When True, SL should be moved to entry price.
        """
        if not entry_price or not current_price:
            return False

        if side == "long":
            profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            profit_pct = (entry_price - current_price) / entry_price

        if profit_pct >= config.BREAKEVEN_TRIGGER_PCT:
            logger.info(
                f"Breakeven triggered! Profit: {profit_pct*100:.2f}% >= "
                f"{config.BREAKEVEN_TRIGGER_PCT*100:.1f}% — "
                f"Moving SL to entry price: {entry_price}"
            )
            return True

        return False

    # ---------------------------------------------------------------
    # RUN ALL PRE-ENTRY CHECKS
    # ---------------------------------------------------------------
    def run_all_checks(self, product_id=None):
        """
        Run all safety filters before placing a new trade.

        Returns:
            (all_passed: bool, results: dict)
        """
        results = {}
        all_passed = True

        # 1. News Filter
        news_safe, news_reason = self.check_news_filter()
        results["news"] = {"passed": news_safe, "reason": news_reason}
        if not news_safe:
            all_passed = False

        # 2. Spread Guard
        spread_safe, spread_pct, spread_reason = self.check_spread()
        results["spread"] = {
            "passed": spread_safe,
            "spread_pct": spread_pct,
            "reason": spread_reason,
        }
        if not spread_safe:
            all_passed = False

        # 3. Max 1 Active Trade
        trade_safe, trade_reason = self.check_max_trades(product_id)
        results["max_trades"] = {"passed": trade_safe, "reason": trade_reason}
        if not trade_safe:
            all_passed = False

        if all_passed:
            logger.info("✅ All safety filters PASSED")
        else:
            failed = [k for k, v in results.items() if not v["passed"]]
            logger.warning(f"❌ Safety filters FAILED: {', '.join(failed)}")

        return all_passed, results
