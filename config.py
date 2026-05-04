"""
BTC Global Elite Scalper V6 — Central Configuration
All strategy parameters, risk settings, and API config in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# MODE
# ============================================================
MODE = os.getenv("MODE", "testnet")  # "testnet" or "production"

# ============================================================
# DELTA EXCHANGE API
# ============================================================
DELTA_API_KEY = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
DELTA_BASE_URL = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")

# Product symbol for BTC/USD Perpetual Futures (Delta Exchange India)
SYMBOL = "BTCUSD"

# ============================================================
# STRATEGY PARAMETERS
# ============================================================
TIMEFRAME = "3m"               # 3-minute candles
CANDLE_FETCH_COUNT = 250       # Number of candles to fetch for indicator calculation
POLL_INTERVAL_SECONDS = 60     # Check every 1 minute for new 3m candle closes

# --- UT Bot Alerts ---
UT_BOT_KEY_VALUE = 2.0         # Sensitivity multiplier
UT_BOT_ATR_PERIOD = 10         # ATR lookback period

# --- Schaff Trend Cycle (STC) ---
STC_CYCLE_LENGTH = 12          # Cycle length
STC_FAST_LENGTH = 26           # Fast EMA period
STC_SLOW_LENGTH = 50           # Slow EMA period

# --- EMA Trend Filter ---
EMA_PERIOD = 200               # 200-period EMA for trend direction

# ============================================================
# ENTRY CONDITIONS
# ============================================================
# LONG:  Price > EMA200 AND UT Bot BUY AND STC > 25
# SHORT: Price < EMA200 AND UT Bot SELL AND STC < 75
STC_LONG_THRESHOLD = 25
STC_SHORT_THRESHOLD = 75

# ============================================================
# RISK MANAGEMENT
# ============================================================
LEVERAGE = 10                  # 10x leverage
MARGIN_PERCENT = 0.15          # Use 15% of balance as margin
MAX_DAILY_DRAWDOWN = 0.05      # Lock bot if 5% daily loss
DAILY_LOCK_HOURS = 24          # Lock duration after hitting drawdown

# ============================================================
# SAFETY FILTERS
# ============================================================
SPREAD_THRESHOLD_PCT = 0.0005  # Max spread: 0.05%
TIMEOUT_MINUTES = 45           # Close trade if stuck for 45 min
MAX_ACTIVE_TRADES = 1          # Only 1 trade at a time
BREAKEVEN_TRIGGER_PCT = 0.005  # Move SL to entry at 0.5% profit
NEWS_BUFFER_MINUTES = 30       # Pause 30 min before/after high-impact news

# ============================================================
# EXECUTION
# ============================================================
CHASE_WAIT_SECONDS = 5         # Wait before re-pricing limit order
CHASE_MAX_ATTEMPTS = 3         # Max price chase attempts
CHASE_TICK_OFFSET = 1          # Move price by 1 tick when chasing

# ============================================================
# PARTIAL TAKE PROFIT & TRAILING STOP
# ============================================================
PARTIAL_TP_PCT = 0.01          # Close 50% at 1% profit
PARTIAL_TP_SIZE_RATIO = 0.5    # Close this fraction of position
FULL_TP_PCT = 0.02             # Target 2% for remaining 50%
TRAILING_SL_ACTIVATION = 0.01  # Activate trailing SL at 1% profit
TRAILING_SL_OFFSET_PCT = 0.005 # Trail by 0.5% from peak

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# DATABASE (Supabase PostgreSQL)
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ============================================================
# FINNHUB (News Calendar)
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
# RENDER / DEPLOYMENT
# ============================================================
RENDER_APP_URL = os.getenv("RENDER_APP_URL", "")
KEEP_ALIVE_INTERVAL = 300      # Ping self every 5 minutes
FLASK_PORT = int(os.getenv("PORT", 5000))

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = "INFO"
MAX_LOG_ENTRIES = 500          # Keep last 500 log entries in memory for dashboard
