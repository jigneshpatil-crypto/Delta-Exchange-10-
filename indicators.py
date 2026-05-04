"""
BTC Global Elite Scalper V6 — Technical Indicators
UT Bot Alerts, Schaff Trend Cycle (STC), EMA 200
All calculated internally from OHLCV data — no TradingView needed.
"""

import numpy as np
import pandas as pd
import logging

import config

logger = logging.getLogger("Indicators")


def calculate_atr(df, period=10):
    """
    Calculate Average True Range (Wilder's method).
    Expects DataFrame with 'high', 'low', 'close' columns.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing (RMA)
    atr = pd.Series(np.nan, index=df.index)
    atr.iloc[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(tr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

    return atr


def calculate_ema(series, period):
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_ut_bot_alerts(df, key_value=None, atr_period=None):
    """
    UT Bot Alerts Indicator.
    Based on ATR Trailing Stop with crossover detection.

    Parameters:
        df: DataFrame with 'high', 'low', 'close' columns
        key_value: Sensitivity multiplier (default from config)
        atr_period: ATR lookback period (default from config)

    Returns:
        DataFrame with added columns:
        - 'ut_atr': ATR values
        - 'ut_trail': Trailing stop line
        - 'ut_signal': 'BUY', 'SELL', or None
    """
    key_value = key_value or config.UT_BOT_KEY_VALUE
    atr_period = atr_period or config.UT_BOT_ATR_PERIOD

    close = df["close"].values
    atr = calculate_atr(df, atr_period).values

    n = len(close)
    nloss = key_value * atr
    trail = np.zeros(n)
    signal = [None] * n

    # Initialize first valid point
    first_valid = atr_period  # First index where ATR is available
    if first_valid < n:
        trail[first_valid] = close[first_valid] - nloss[first_valid]

    # Calculate trailing stop recursively
    for i in range(first_valid + 1, n):
        if np.isnan(nloss[i]):
            trail[i] = trail[i - 1]
            continue

        prev_trail = trail[i - 1]
        prev_close = close[i - 1]
        curr_close = close[i]
        curr_nloss = nloss[i]

        # Determine new trailing stop
        if curr_close > prev_trail:
            # Price above trail → uptrend
            trail[i] = max(prev_trail, curr_close - curr_nloss)
        elif curr_close < prev_trail:
            # Price below trail → downtrend
            trail[i] = min(prev_trail, curr_close + curr_nloss)
        else:
            trail[i] = prev_trail

        # Detect crossovers for signals
        if curr_close > trail[i] and prev_close <= trail[i - 1]:
            signal[i] = "BUY"
        elif curr_close < trail[i] and prev_close >= trail[i - 1]:
            signal[i] = "SELL"

    df = df.copy()
    df["ut_atr"] = atr
    df["ut_trail"] = trail
    df["ut_signal"] = signal

    return df


def calculate_stc(df, cycle_length=None, fast_length=None, slow_length=None):
    """
    Schaff Trend Cycle (STC) Indicator.
    Combines MACD with double-smoothed Stochastic.

    Parameters:
        df: DataFrame with 'close' column
        cycle_length: STC cycle period (default from config)
        fast_length: Fast EMA period (default from config)
        slow_length: Slow EMA period (default from config)

    Returns:
        DataFrame with added column:
        - 'stc': STC values (0-100)
    """
    cycle_length = cycle_length or config.STC_CYCLE_LENGTH
    fast_length = fast_length or config.STC_FAST_LENGTH
    slow_length = slow_length or config.STC_SLOW_LENGTH

    close = df["close"]

    # Step 1: Calculate MACD line
    ema_fast = calculate_ema(close, fast_length)
    ema_slow = calculate_ema(close, slow_length)
    macd = ema_fast - ema_slow

    # Step 2: First Stochastic on MACD
    macd_min = macd.rolling(window=cycle_length, min_periods=1).min()
    macd_max = macd.rolling(window=cycle_length, min_periods=1).max()

    denom = macd_max - macd_min
    denom = denom.replace(0, np.nan)

    stoch_k = 100.0 * (macd - macd_min) / denom
    stoch_k = stoch_k.fillna(50)  # Default to 50 when range is 0

    # Step 3: Smooth %K to get %D (first smoothing)
    stoch_d = calculate_ema(stoch_k, cycle_length)

    # Step 4: Second Stochastic on %D
    stoch_d_min = stoch_d.rolling(window=cycle_length, min_periods=1).min()
    stoch_d_max = stoch_d.rolling(window=cycle_length, min_periods=1).max()

    denom2 = stoch_d_max - stoch_d_min
    denom2 = denom2.replace(0, np.nan)

    stoch_k2 = 100.0 * (stoch_d - stoch_d_min) / denom2
    stoch_k2 = stoch_k2.fillna(50)

    # Step 5: Final smoothing → STC
    stc = calculate_ema(stoch_k2, cycle_length)
    stc = stc.clip(0, 100)

    df = df.copy()
    df["stc"] = stc

    return df


def calculate_ema_200(df, period=None):
    """
    EMA 200 Trend Filter.

    Returns:
        DataFrame with added column:
        - 'ema200': EMA 200 values
    """
    period = period or config.EMA_PERIOD
    df = df.copy()
    df["ema200"] = calculate_ema(df["close"], period)
    return df


def calculate_all_indicators(df):
    """
    Calculate all indicators at once.
    Expects DataFrame with columns: 'timestamp', 'open', 'high', 'low', 'close', 'volume'

    Returns:
        DataFrame with all indicator columns added:
        - ut_atr, ut_trail, ut_signal
        - stc
        - ema200
    """
    logger.debug(f"Calculating indicators on {len(df)} candles")

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Calculate each indicator
    df = calculate_ut_bot_alerts(df)
    df = calculate_stc(df)
    df = calculate_ema_200(df)

    return df


def get_current_signal(df):
    """
    Evaluate the latest candle for entry signals.

    Returns dict:
        {
            'signal': 'LONG' | 'SHORT' | None,
            'ut_signal': 'BUY' | 'SELL' | None,
            'stc': float,
            'ema200': float,
            'close': float,
            'reason': str
        }
    """
    if df is None or len(df) < 2:
        return {"signal": None, "reason": "Insufficient data"}

    latest = df.iloc[-1]
    close = latest["close"]
    ema200 = latest["ema200"]
    stc = latest["stc"]
    ut_signal = latest["ut_signal"]

    result = {
        "signal": None,
        "ut_signal": ut_signal,
        "stc": round(stc, 2) if not np.isnan(stc) else None,
        "ema200": round(ema200, 2) if not np.isnan(ema200) else None,
        "close": round(close, 2),
        "reason": "",
    }

    # LONG Condition: Price > EMA200 AND UT Bot BUY AND STC > 25
    if (
        close > ema200
        and ut_signal == "BUY"
        and stc > config.STC_LONG_THRESHOLD
    ):
        result["signal"] = "LONG"
        result["reason"] = (
            f"LONG: Close({close:.2f}) > EMA200({ema200:.2f}), "
            f"UT Bot=BUY, STC({stc:.1f}) > {config.STC_LONG_THRESHOLD}"
        )
        logger.info(result["reason"])

    # SHORT Condition: Price < EMA200 AND UT Bot SELL AND STC < 75
    elif (
        close < ema200
        and ut_signal == "SELL"
        and stc < config.STC_SHORT_THRESHOLD
    ):
        result["signal"] = "SHORT"
        result["reason"] = (
            f"SHORT: Close({close:.2f}) < EMA200({ema200:.2f}), "
            f"UT Bot=SELL, STC({stc:.1f}) < {config.STC_SHORT_THRESHOLD}"
        )
        logger.info(result["reason"])

    else:
        reasons = []
        if ut_signal is None:
            reasons.append("No UT Bot signal")
        if close > ema200:
            reasons.append(f"Price above EMA200 (bullish bias)")
        else:
            reasons.append(f"Price below EMA200 (bearish bias)")
        reasons.append(f"STC={stc:.1f}")
        result["reason"] = "No signal: " + ", ".join(reasons)

    return result
