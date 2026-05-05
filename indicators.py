"""
Heikin-Ashi + Chandelier Exit + LSMA Filter — Technical Indicators
All calculated internally from OHLCV data — no TradingView needed.

Indicators:
  1. Heikin-Ashi candles (for exit signal — Red candle detection)
  2. Chandelier Exit (for entry signal — Green/Bullish flip)
  3. LSMA 25 (Least Squares Moving Average as trend filter)
"""

import numpy as np
import pandas as pd
import logging

import config

logger = logging.getLogger("Indicators")


# ================================================================
# 1. HEIKIN-ASHI CANDLES
# ================================================================
def calculate_heikin_ashi(df):
    """
    Calculate Heikin-Ashi candles from standard OHLCV.

    Heikin-Ashi formulas:
        HA_Close = (Open + High + Low + Close) / 4
        HA_Open  = (prev_HA_Open + prev_HA_Close) / 2  (first = (O+C)/2)
        HA_High  = max(High, HA_Open, HA_Close)
        HA_Low   = min(Low, HA_Open, HA_Close)

    Adds columns: ha_open, ha_high, ha_low, ha_close, ha_color ('green' / 'red')
    """
    df = df.copy()
    n = len(df)

    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

    ha_open = pd.Series(np.zeros(n), index=df.index)
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0

    for i in range(1, n):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0

    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)

    df["ha_open"] = ha_open
    df["ha_high"] = ha_high
    df["ha_low"] = ha_low
    df["ha_close"] = ha_close

    # Color: green if close >= open, red otherwise
    df["ha_color"] = np.where(ha_close >= ha_open, "green", "red")

    return df


# ================================================================
# 2. CHANDELIER EXIT
# ================================================================
def calculate_atr(df, period=22):
    """
    Calculate Average True Range using Wilder's smoothing (RMA).
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
    if len(tr) >= period:
        atr.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(tr)):
            atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period

    return atr


def calculate_chandelier_exit(df, atr_period=None, atr_mult=None):
    """
    Chandelier Exit Indicator.

    Long Stop  = Highest High(n) - ATR(n) * multiplier
    Short Stop = Lowest Low(n)  + ATR(n) * multiplier

    Signal flips:
        - GREEN (bullish) when close crosses above the short stop
          (i.e., price reverses upward → buy signal)
        - RED (bearish) when close crosses below the long stop
          (i.e., price breaks downward → sell signal)

    Adds columns:
        - ce_atr          : ATR values
        - ce_long_stop    : Chandelier long trailing stop
        - ce_short_stop   : Chandelier short trailing stop
        - ce_direction    : 1 = bullish (green), -1 = bearish (red)
        - ce_signal       : 'BUY' on flip to green, 'SELL' on flip to red, else None
    """
    atr_period = atr_period or config.CE_ATR_PERIOD
    atr_mult = atr_mult or config.CE_ATR_MULTIPLIER

    df = df.copy()
    atr = calculate_atr(df, atr_period)
    df["ce_atr"] = atr

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    atr_vals = atr.values
    n = len(df)

    long_stop = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    signal = [None] * n

    # We need at least atr_period candles to start
    start = atr_period

    # Initialize first valid values
    if start < n:
        highest = np.max(high[:start + 1])
        lowest = np.min(low[:start + 1])
        long_stop[start] = highest - atr_vals[start] * atr_mult
        short_stop[start] = lowest + atr_vals[start] * atr_mult
        direction[start] = 1 if close[start] > long_stop[start] else -1

    for i in range(start + 1, n):
        if np.isnan(atr_vals[i]):
            long_stop[i] = long_stop[i - 1]
            short_stop[i] = short_stop[i - 1]
            direction[i] = direction[i - 1]
            continue

        # Rolling highest high and lowest low over atr_period
        window_start = max(0, i - atr_period + 1)
        highest = np.max(high[window_start:i + 1])
        lowest = np.min(low[window_start:i + 1])

        # Calculate raw stops
        raw_long_stop = highest - atr_vals[i] * atr_mult
        raw_short_stop = lowest + atr_vals[i] * atr_mult

        # Long stop can only move up (ratchet)
        if close[i - 1] > long_stop[i - 1]:
            long_stop[i] = max(raw_long_stop, long_stop[i - 1])
        else:
            long_stop[i] = raw_long_stop

        # Short stop can only move down (ratchet)
        if close[i - 1] < short_stop[i - 1]:
            short_stop[i] = min(raw_short_stop, short_stop[i - 1])
        else:
            short_stop[i] = raw_short_stop

        # Direction logic
        prev_dir = direction[i - 1]
        if prev_dir == 1:
            # Was bullish — check if broken below long stop
            if close[i] < long_stop[i]:
                direction[i] = -1  # Flip to bearish
            else:
                direction[i] = 1
        else:
            # Was bearish — check if broken above short stop
            if close[i] > short_stop[i]:
                direction[i] = 1  # Flip to bullish
            else:
                direction[i] = -1

        # Detect flips
        if direction[i] == 1 and direction[i - 1] == -1:
            signal[i] = "BUY"   # Flipped to GREEN
        elif direction[i] == -1 and direction[i - 1] == 1:
            signal[i] = "SELL"  # Flipped to RED

    df["ce_long_stop"] = long_stop
    df["ce_short_stop"] = short_stop
    df["ce_direction"] = direction
    df["ce_signal"] = signal

    return df


# ================================================================
# 3. LSMA (Least Squares Moving Average)
# ================================================================
def calculate_lsma(df, period=None):
    """
    Least Squares Moving Average (LSMA) — also called Linear Regression Value.

    For each bar, fit a linear regression line to the last `period` closing prices,
    and take the endpoint of that line as the LSMA value.

    Adds column: lsma
    """
    period = period or config.LSMA_PERIOD
    close = df["close"].values
    n = len(close)
    lsma = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = close[i - period + 1: i + 1]
        x = np.arange(period)
        # Linear regression: y = a + b*x
        # LSMA = value at x = period - 1 (the last point)
        x_mean = x.mean()
        y_mean = window.mean()
        ss_xx = np.sum((x - x_mean) ** 2)
        ss_xy = np.sum((x - x_mean) * (window - y_mean))
        if ss_xx != 0:
            b = ss_xy / ss_xx
            a = y_mean - b * x_mean
            lsma[i] = a + b * (period - 1)
        else:
            lsma[i] = y_mean

    df = df.copy()
    df["lsma"] = lsma
    return df


# ================================================================
# COMBINED: Calculate All Indicators
# ================================================================
def calculate_all_indicators(df):
    """
    Calculate all indicators at once.
    Expects DataFrame with columns: timestamp, open, high, low, close, volume

    Returns DataFrame with added indicator columns:
        - ha_open, ha_high, ha_low, ha_close, ha_color
        - ce_atr, ce_long_stop, ce_short_stop, ce_direction, ce_signal
        - lsma
    """
    logger.debug(f"Calculating indicators on {len(df)} candles")

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 1. Heikin-Ashi
    df = calculate_heikin_ashi(df)

    # 2. Chandelier Exit
    df = calculate_chandelier_exit(df)

    # 3. LSMA
    df = calculate_lsma(df)

    return df


# ================================================================
# SIGNAL EVALUATION
# ================================================================
def get_current_signal(df):
    """
    Evaluate the latest candle for entry/exit signals.

    ENTRY (LONG):
        Chandelier Exit flips to GREEN (ce_signal == 'BUY')
        AND Close > LSMA 25

    EXIT (close long):
        Heikin-Ashi candle turns RED (ha_color == 'red')
        AND Close < LSMA 25

    Returns dict:
        {
            'signal': 'LONG' | 'EXIT' | None,
            'ce_signal': 'BUY' | 'SELL' | None,
            'ce_direction': 1 (green) | -1 (red),
            'ha_color': 'green' | 'red',
            'lsma': float,
            'close': float,
            'reason': str
        }
    """
    if df is None or len(df) < 2:
        return {"signal": None, "reason": "Insufficient data"}

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(latest["close"])
    lsma = float(latest["lsma"]) if not np.isnan(latest["lsma"]) else None
    ha_color = latest["ha_color"]
    ce_signal = latest["ce_signal"]
    ce_direction = int(latest["ce_direction"])

    result = {
        "signal": None,
        "ce_signal": ce_signal,
        "ce_direction": ce_direction,
        "ha_color": ha_color,
        "lsma": round(lsma, 2) if lsma is not None else None,
        "close": round(close, 2),
        "reason": "",
    }

    if lsma is None:
        result["reason"] = "LSMA not yet available (need more candle data)"
        return result

    # --- ENTRY (LONG) ---
    # Chandelier Exit flips to GREEN AND Close > LSMA 25
    if ce_signal == "BUY" and close > lsma:
        result["signal"] = "LONG"
        result["reason"] = (
            f"LONG ENTRY: Chandelier Exit flipped GREEN, "
            f"Close({close:.2f}) > LSMA25({lsma:.2f})"
        )
        logger.info(result["reason"])
        return result

    # --- EXIT (Close Long) ---
    # Heikin-Ashi turns RED AND Close < LSMA 25
    if ha_color == "red" and close < lsma:
        result["signal"] = "EXIT"
        result["reason"] = (
            f"EXIT SIGNAL: HA candle RED, "
            f"Close({close:.2f}) < LSMA25({lsma:.2f})"
        )
        logger.info(result["reason"])
        return result

    # --- No signal ---
    reasons = []
    if ce_direction == 1:
        reasons.append("CE: Bullish (green)")
    else:
        reasons.append("CE: Bearish (red)")
    reasons.append(f"HA: {ha_color}")
    if close > lsma:
        reasons.append(f"Close({close:.2f}) > LSMA({lsma:.2f})")
    else:
        reasons.append(f"Close({close:.2f}) < LSMA({lsma:.2f})")
    result["reason"] = "No signal: " + ", ".join(reasons)

    return result
