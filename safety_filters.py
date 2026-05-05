"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Safety Filters
Pyramiding guard, spread check, and news filter for safe execution.
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests

import config

logger = logging.getLogger("SafetyFilters")


class SafetyFilters:
    """Pre-entry safety checks. Must all pass before placing a trade."""

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

                if country != "US":
                    continue
                if impact not in ("high", "3"):
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
            return self._news_cache

    def check_news_filter(self):
        """
        Returns (is_safe, reason).
        Blocks trading 30 min before and after high-impact news.
        """
        events = self._fetch_economic_calendar()
        if not events:
            return True, "No high-impact news events"

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=30)

        for event in events:
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

            if (event_dt - buffer) <= now <= (event_dt + buffer):
                event_name = event.get("event", "Unknown")
                reason = (
                    f"Skipping trade — High Impact News: "
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
        Blocks if bid-ask spread > threshold.
        """
        orderbook = self.client.get_orderbook()
        if not orderbook:
            return False, 0, "Failed to fetch orderbook"

        try:
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
    # 3. PYRAMIDING GUARD (Max 1 Active Trade)
    # ---------------------------------------------------------------
    def check_no_active_position(self, product_id=None):
        """
        Returns (is_safe, reason).
        STRICTLY blocks if there's already an active position (pyramiding = 1).
        """
        pos = self.client.get_position(product_id)
        if pos and pos["size"] != 0:
            reason = (
                f"Active position exists (pyramiding=1, blocked) — "
                f"{pos['side'].upper()} size={abs(pos['size'])} "
                f"@ ${pos['entry_price']}, "
                f"P&L: {pos['unrealized_pnl']}"
            )
            logger.info(reason)
            return False, reason

        return True, "No active position — entry allowed"

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

        # 1. Pyramiding Guard (most important)
        pos_safe, pos_reason = self.check_no_active_position(product_id)
        results["pyramiding"] = {"passed": pos_safe, "reason": pos_reason}
        if not pos_safe:
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

        # 3. News Filter
        news_safe, news_reason = self.check_news_filter()
        results["news"] = {"passed": news_safe, "reason": news_reason}
        if not news_safe:
            all_passed = False

        if all_passed:
            logger.info("✅ All safety filters PASSED")
        else:
            failed = [k for k, v in results.items() if not v["passed"]]
            logger.warning(f"❌ Safety filters FAILED: {', '.join(failed)}")

        return all_passed, results
