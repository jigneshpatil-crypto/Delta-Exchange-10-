"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Central Configuration
All strategy parameters, risk settings, and API config in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# MODE
# ============================================================
MODE = os.getenv("MODE", "production")  # "testnet" or "production"

# ============================================================
# PROXY CONFIGURATION
# ============================================================
PROXY_URL = os.getenv("PROXY_URL", "http://ifvlvxhc:zhkk5r1pn2n5@142.111.67.146:5611")


# ============================================================
# DELTA EXCHANGE API  (DO NOT MODIFY — retained from old setup)
# ============================================================
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "").strip()
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "").strip()
DELTA_BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").strip()

# Product symbol — BTC/USD Perpetual Futures (Delta Exchange India uses BTCUSD)
SYMBOL = "BTCUSD"

# ============================================================
# STRATEGY PARAMETERS
# ============================================================
STRATEGY_NAME = "Heikin-Ashi + Chandelier Exit + LSMA Filter"
TIMEFRAME = "5m"                # 5-minute candles
CANDLE_FETCH_COUNT = 300        # Number of candles to fetch for indicator warmup
POLL_INTERVAL_SECONDS = 30      # Check every 30s for new 5m candle closes

# --- Trade Direction ---
TRADE_DIRECTION = "LONG"        # LONG only. Do NOT take Short trades.

# --- Chandelier Exit ---
CE_ATR_PERIOD = 22              # ATR lookback period for Chandelier Exit
CE_ATR_MULTIPLIER = 3.0         # ATR multiplier

# --- LSMA (Least Squares Moving Average) ---
LSMA_PERIOD = 25                # LSMA lookback period

# --- Heikin-Ashi ---
# Calculated from raw OHLCV — no config needed

# ============================================================
# ENTRY / EXIT CONDITIONS
# ============================================================
# ENTRY (Buy/Long):
#   Chandelier Exit flips to GREEN (bullish)
#   AND Close Price > LSMA 25
#
# EXIT (Sell/Close Long):
#   Heikin-Ashi candle turns RED
#   AND Close Price < LSMA 25

# ============================================================
# ORDER EXECUTION — MARKET ORDERS ONLY
# ============================================================
ORDER_TYPE = "market_order"       # MARKET ORDERS ONLY
LIMIT_BUFFER_PCT = 0.0005       # 0.05% buffer (kept for SL calculation if needed)
ORDER_TIMEOUT_MINUTES = 0       # Not used for market orders
ORDER_TIMEOUT_SECONDS = 0       # Not used for market orders

# ============================================================
# RISK MANAGEMENT
# ============================================================
LEVERAGE = 50                   # 50x Isolated leverage (max profit on small capital)
CAPITAL_PER_TRADE = 10.0        # $10 per trade (100% of small balance)
PYRAMIDING = 1                  # STRICTLY 1 — no multiple positions at the same time
HARD_STOP_LOSS_PCT = 0.015      # 1.5% hard SL below entry (at 50x this = 75% account loss)

# ============================================================
# DAILY DRAWDOWN PROTECTION
# ============================================================
MAX_DAILY_DRAWDOWN = 0.30       # 30% daily loss limit (e.g., $3 on $10 account)
DAILY_LOCK_HOURS = 24           # Pause bot for 24 hours after hitting drawdown

# ============================================================
# SAFETY FILTERS
# ============================================================
SPREAD_THRESHOLD_PCT = 0.001    # Max spread: 0.1% (relaxed for 5m)
MAX_ACTIVE_TRADES = 1           # Only 1 trade at a time (pyramiding = 1)

# ============================================================
# TELEGRAM  (DO NOT MODIFY — retained from old setup)
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# DATABASE (Neon PostgreSQL)  (DO NOT MODIFY — retained)
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ============================================================
# FINNHUB (News Calendar)  (DO NOT MODIFY — retained)
# ============================================================
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# High-impact news events to filter
HIGH_IMPACT_EVENTS = [
    "CPI", "Consumer Price Index",
    "FOMC", "Federal Funds Rate", "Interest Rate Decision",
    "Nonfarm Payrolls", "Non-Farm Payrolls", "NFP",
    "Jobs", "Employment", "Unemployment Rate",
    "GDP", "Gross Domestic Product",
    "PPI", "Producer Price Index",
    "Retail Sales",
]

# ============================================================
# RENDER / DEPLOYMENT  (DO NOT MODIFY — retained)
# ============================================================
RENDER_APP_URL = os.getenv("RENDER_APP_URL", "")
KEEP_ALIVE_INTERVAL = 300       # Ping self every 5 minutes
FLASK_PORT = int(os.getenv("PORT", 5000))

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = "INFO"
MAX_LOG_ENTRIES = 500           # Keep last 500 log entries in memory for dashboard
