"""
BTC Global Elite Scalper V6 — IMPROVED Daily Backtest
Adapted for daily timeframe with realistic targets.
Uses trail direction + STC momentum for more signals.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# DAILY-ADAPTED PARAMETERS
# ============================================================
EMA_PERIOD = 200

# ATR & UT Bot
UT_BOT_KEY_VALUE = 2.0
UT_BOT_ATR_PERIOD = 14

# STC
STC_CYCLE_LENGTH = 10
STC_FAST_LENGTH = 23
STC_SLOW_LENGTH = 50
STC_LONG_THRESHOLD = 30        # Higher threshold
STC_SHORT_THRESHOLD = 70       # Lower threshold

LEVERAGE = 10
MARGIN_PERCENT = 0.15

# TP targets adapted for daily
PARTIAL_TP_PCT = 0.015         # 1.5%
PARTIAL_TP_SIZE_RATIO = 0.5
FULL_TP_PCT = 0.03             # 3%

# ATR-based SL (wider for daily)
ATR_SL_MULT = 3.0              # 3x ATR

BREAKEVEN_TRIGGER_PCT = 0.01   # Move to BE at 1%
TRAILING_SL_OFFSET_PCT = 0.01

TIMEOUT_DAYS = 14

# Filters (tighter for better accuracy)
RSI_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 25

MAX_TRADES_PER_MONTH = 4       # Monthly limit
INITIAL_BALANCE = 100.0

# ============================================================
# INDICATORS
# ============================================================

def calculate_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = pd.Series(np.nan, index=df.index)
    atr.iloc[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(tr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_adx(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = calculate_atr(df, period)
    plus_di = 100 * plus_dm.rolling(window=period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.rolling(window=period, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window=period, min_periods=period).mean()

def calculate_stc(df, cycle_length=10, fast_length=23, slow_length=50):
    close = df["close"]
    ema_fast = calculate_ema(close, fast_length)
    ema_slow = calculate_ema(close, slow_length)
    macd = ema_fast - ema_slow
    macd_min = macd.rolling(window=cycle_length, min_periods=1).min()
    macd_max = macd.rolling(window=cycle_length, min_periods=1).max()
    denom = macd_max - macd_min
    denom = denom.replace(0, np.nan)
    stoch_k = 100.0 * (macd - macd_min) / denom
    stoch_k = stoch_k.fillna(50)
    stoch_d = calculate_ema(stoch_k, cycle_length)
    stoch_d_min = stoch_d.rolling(window=cycle_length, min_periods=1).min()
    stoch_d_max = stoch_d.rolling(window=cycle_length, min_periods=1).max()
    denom2 = stoch_d_max - stoch_d_min
    denom2 = denom2.replace(0, np.nan)
    stoch_k2 = 100.0 * (stoch_d - stoch_d_min) / denom2
    stoch_k2 = stoch_k2.fillna(50)
    stc = calculate_ema(stoch_k2, cycle_length)
    stc = stc.clip(0, 100)
    return stc

def calculate_ut_bot_trail(df, key_value=2.0, atr_period=14):
    """Returns trail line and direction (bullish/bearish)"""
    close = df["close"].values
    atr = calculate_atr(df, atr_period).values
    n = len(close)
    nloss = key_value * atr
    trail = np.zeros(n)
    first_valid = atr_period
    if first_valid < n:
        trail[first_valid] = close[first_valid] - nloss[first_valid]
    for i in range(first_valid + 1, n):
        if np.isnan(nloss[i]):
            trail[i] = trail[i - 1]
            continue
        prev_trail = trail[i - 1]
        prev_close = close[i - 1]
        curr_close = close[i]
        curr_nloss = nloss[i]
        if curr_close > prev_trail:
            trail[i] = max(prev_trail, curr_close - curr_nloss)
        elif curr_close < prev_trail:
            trail[i] = min(prev_trail, curr_close + curr_nloss)
        else:
            trail[i] = prev_trail
    df = df.copy()
    df["ut_trail"] = trail
    df["ut_atr"] = atr
    return df

def calculate_all_indicators(df):
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = calculate_ut_bot_trail(df)
    df["stc"] = calculate_stc(df)
    df["ema200"] = calculate_ema(df["close"], 200)
    df["rsi"] = calculate_rsi(df["close"], RSI_PERIOD)
    df["adx"] = calculate_adx(df, ADX_PERIOD)
    return df

# ============================================================
# DATA
# ============================================================

def fetch_data():
    import yfinance as yf
    print("Fetching daily BTC-USD data (Jan 2025 - Apr 2026)...")
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start="2025-01-01", end="2026-05-05", interval="1d")
    if df.empty:
        print("ERROR: No data")
        return None
    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.columns = ["open", "high", "low", "close", "volume"]
    print(f"  Candles: {len(df)} | Range: {df.index[0].date()} to {df.index[-1].date()}")
    return df

# ============================================================
# BACKTEST
# ============================================================

class BacktestEngine:
    def __init__(self, df, initial_balance=100.0):
        self.df = df
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trades = []
        self.current_trade = None
        self.monthly_pnl = {}
        self.monthly_win = {}
        self.monthly_loss = {}
        self.monthly_trade_count = {}
        self.equity_curve = []

    def get_month_key(self, ts):
        return ts.strftime("%Y-%m")

    def manage_trade(self, idx, row):
        if not self.current_trade:
            return

        entry_price = self.current_trade["entry_price"]
        side = self.current_trade["side"]
        entry_idx = self.current_trade["entry_idx"]
        current_price = row["close"]
        current_ts = self.df.index[idx]
        entry_ts = self.df.index[entry_idx]
        elapsed_days = (current_ts - entry_ts).days

        # Update peak
        if side == "long":
            self.current_trade["peak"] = max(self.current_trade["peak"], current_price)
        else:
            self.current_trade["peak"] = min(self.current_trade["peak"], current_price)
        peak = self.current_trade["peak"]

        if side == "long":
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        # ATR-based SL check
        sl_price = self.current_trade["sl_price"]
        if sl_price is not None:
            if side == "long" and current_price <= sl_price:
                pnl = (sl_price - entry_price) / entry_price * self.current_trade["margin"] * LEVERAGE
                pnl += self.current_trade.get("partial_tp_pnl", 0)
                self.balance += pnl
                self.record_trade(idx, sl_price, "sl_hit", pnl)
                return
            elif side == "short" and current_price >= sl_price:
                pnl = (entry_price - sl_price) / entry_price * self.current_trade["margin"] * LEVERAGE
                pnl += self.current_trade.get("partial_tp_pnl", 0)
                self.balance += pnl
                self.record_trade(idx, sl_price, "sl_hit", pnl)
                return

        # Timeout
        if elapsed_days >= TIMEOUT_DAYS:
            pnl = profit_pct * self.current_trade["margin"] * LEVERAGE
            pnl += self.current_trade.get("partial_tp_pnl", 0)
            self.balance += pnl
            self.record_trade(idx, current_price, "timeout", pnl)
            return

        # Breakeven
        if not self.current_trade["breakeven_done"] and profit_pct >= BREAKEVEN_TRIGGER_PCT:
            self.current_trade["breakeven_done"] = True
            self.current_trade["sl_price"] = entry_price

        # Partial TP
        if not self.current_trade["partial_tp_done"] and profit_pct >= PARTIAL_TP_PCT:
            partial_pnl = profit_pct * self.current_trade["margin"] * LEVERAGE * PARTIAL_TP_SIZE_RATIO
            self.balance += partial_pnl
            self.current_trade["partial_tp_pnl"] = partial_pnl
            self.current_trade["partial_tp_done"] = True
            self.current_trade["trailing_active"] = True

        # Trailing SL
        if self.current_trade["trailing_active"]:
            if side == "long":
                trailing_sl = peak * (1 - TRAILING_SL_OFFSET_PCT)
                if current_price <= trailing_sl:
                    rem = (current_price - entry_price) / entry_price * self.current_trade["margin"] * LEVERAGE * PARTIAL_TP_SIZE_RATIO
                    total = self.current_trade.get("partial_tp_pnl", 0) + rem
                    self.balance += total
                    self.record_trade(idx, current_price, "trailing_sl", total)
                    return
            else:
                trailing_sl = peak * (1 + TRAILING_SL_OFFSET_PCT)
                if current_price >= trailing_sl:
                    rem = (entry_price - current_price) / entry_price * self.current_trade["margin"] * LEVERAGE * PARTIAL_TP_SIZE_RATIO
                    total = self.current_trade.get("partial_tp_pnl", 0) + rem
                    self.balance += total
                    self.record_trade(idx, current_price, "trailing_sl", total)
                    return

        # Full TP
        if self.current_trade["partial_tp_done"] and profit_pct >= FULL_TP_PCT:
            rem = profit_pct * self.current_trade["margin"] * LEVERAGE * PARTIAL_TP_SIZE_RATIO
            total = self.current_trade.get("partial_tp_pnl", 0) + rem
            self.balance += total
            self.record_trade(idx, current_price, "full_tp", total)
            return

    def record_trade(self, idx, exit_price, reason, pnl):
        month_key = self.get_month_key(self.df.index[idx])
        self.monthly_pnl[month_key] = self.monthly_pnl.get(month_key, 0) + pnl
        self.monthly_trade_count[month_key] = self.monthly_trade_count.get(month_key, 0) + 1
        if pnl > 0:
            self.monthly_win[month_key] = self.monthly_win.get(month_key, 0) + 1
        else:
            self.monthly_loss[month_key] = self.monthly_loss.get(month_key, 0) + 1

        self.trades.append({
            "entry_idx": self.current_trade["entry_idx"],
            "exit_idx": idx,
            "entry_time": self.df.index[self.current_trade["entry_idx"]],
            "exit_time": self.df.index[idx],
            "side": self.current_trade["side"],
            "entry_price": self.current_trade["entry_price"],
            "exit_price": exit_price,
            "size": self.current_trade["size"],
            "margin": self.current_trade["margin"],
            "sl_price": self.current_trade.get("sl_price"),
            "pnl": pnl,
            "pnl_pct": (pnl / self.current_trade["margin"] * 100) if self.current_trade["margin"] > 0 else 0,
            "reason": reason,
        })
        self.current_trade = None

    def run(self):
        print(f"\nRunning backtest...")
        print(f"Initial balance: ${self.initial_balance:.2f}")
        print(f"TP: {PARTIAL_TP_PCT*100:.0f}% partial / {FULL_TP_PCT*100:.0f}% full | SL: {ATR_SL_MULT}x ATR")
        print(f"Filters: ADX>{ADX_THRESHOLD}, RSI sweet spot, STC momentum")
        print()

        for idx in range(len(self.df)):
            row = self.df.iloc[idx]
            ts = self.df.index[idx]
            month_key = self.get_month_key(ts)

            if idx < EMA_PERIOD + 20:
                continue

            self.equity_curve.append({"time": ts, "equity": self.balance})

            # Manage open trade
            if self.current_trade:
                self.manage_trade(idx, row)
                continue

            # Monthly trade limit
            if self.monthly_trade_count.get(month_key, 0) >= MAX_TRADES_PER_MONTH:
                continue

            stc = row.get("stc", np.nan)
            ema200 = row.get("ema200", np.nan)
            rsi = row.get("rsi", np.nan)
            adx = row.get("adx", np.nan)
            close = row["close"]
            trail = row.get("ut_trail", 0)
            atr_val = row.get("ut_atr", 0)

            if any(np.isnan(v) for v in [stc, ema200, rsi, adx]):
                continue

            # STC momentum check (is STC rising or falling?)
            if idx > 0:
                prev_stc = self.df.iloc[idx - 1].get("stc", np.nan)
            else:
                prev_stc = stc

            # ADX filter - strong trend only
            if adx < ADX_THRESHOLD:
                continue

            # Check signals - TREND FOLLOWING (LONG only in uptrend, SHORT only in downtrend)
            # LONG: Price > EMA200, Price > UT Trail, STC > 25, STC rising, RSI not overbought
            # SHORT: Price < EMA200, Price < UT Trail, STC < 75, STC falling, RSI not oversold
            signal = None
            if (close > ema200 and close > trail and stc > STC_LONG_THRESHOLD
                    and 20 < rsi < 70 and not np.isnan(prev_stc) and stc > prev_stc):
                signal = "long"
            elif (close < ema200 and close < trail and stc < STC_SHORT_THRESHOLD
                    and 30 < rsi < 80 and not np.isnan(prev_stc) and stc < prev_stc):
                signal = "short"

            if signal:
                margin = self.balance * MARGIN_PERCENT
                notional = margin * LEVERAGE
                size = max(1, int(notional))

                # ATR-based SL
                if signal == "long":
                    sl_price = close - (ATR_SL_MULT * atr_val)
                else:
                    sl_price = close + (ATR_SL_MULT * atr_val)

                self.current_trade = {
                    "entry_idx": idx,
                    "side": signal,
                    "entry_price": close,
                    "size": size,
                    "margin": margin,
                    "peak": close,
                    "breakeven_done": False,
                    "partial_tp_done": False,
                    "partial_tp_pnl": 0,
                    "trailing_active": False,
                    "sl_price": sl_price,
                }

        # Close remaining
        if self.current_trade:
            entry_price = self.current_trade["entry_price"]
            side = self.current_trade["side"]
            last_price = self.df.iloc[-1]["close"]
            if side == "long":
                pnl = (last_price - entry_price) / entry_price * self.current_trade["margin"] * LEVERAGE
            else:
                pnl = (entry_price - last_price) / entry_price * self.current_trade["margin"] * LEVERAGE
            pnl += self.current_trade.get("partial_tp_pnl", 0)
            self.balance += pnl
            self.record_trade(len(self.df) - 1, last_price, "end_of_data", pnl)

        return self.generate_report()

    def generate_report(self):
        trades_df = pd.DataFrame(self.trades)

        print("=" * 85)
        print("   BTC GLOBAL ELITE SCALPER V6 - MONTHLY BACKTEST (Jan 2025 - Apr 2026)")
        print("=" * 85)

        print(f"\nPeriod: {self.df.index[0].date()} to {self.df.index[-1].date()}")
        print(f"Initial: ${self.initial_balance:.2f} | Final: ${self.balance:.2f} | Return: {((self.balance-self.initial_balance)/self.initial_balance)*100:+.2f}%")

        # Monthly table
        print("\n" + "=" * 85)
        print(f"{'Month':<12} {'Trades':>7} {'Wins':>6} {'Losses':>8} {'Win%':>7} {'PnL ($)':>12} {'Cumulative ($)':>16} {'Status':>8}")
        print("-" * 85)

        cumulative = self.initial_balance
        months = []
        for y in range(2025, 2027):
            for m in range(1, 13):
                if y == 2026 and m > 4:
                    break
                months.append(f"{y}-{m:02d}")

        total_wins = 0
        total_losses = 0
        total_trades_count = 0

        for mk in months:
            pnl = self.monthly_pnl.get(mk, 0)
            t_count = self.monthly_trade_count.get(mk, 0)
            wins = self.monthly_win.get(mk, 0)
            losses = self.monthly_loss.get(mk, 0)
            cumulative += pnl

            total_wins += wins
            total_losses += losses
            total_trades_count += t_count

            if t_count == 0:
                print(f"{mk:<12} {t_count:>7} {'':>6} {'':>8} {'':>7} {'No trades':>12} {cumulative:>16.2f} {'':>8}")
                continue

            wr = (wins / t_count * 100) if t_count > 0 else 0
            status = "GREEN" if pnl > 0 else "RED"
            print(f"{mk:<12} {t_count:>7} {wins:>6} {losses:>8} {wr:>6.1f}% {pnl:>+12.2f} {cumulative:>16.2f} {status:>8}")

        print("-" * 85)

        # Overall
        wr_total = (total_wins / total_trades_count * 100) if total_trades_count > 0 else 0
        print(f"\n{'TOTAL':<12} {total_trades_count:>7} {total_wins:>6} {total_losses:>8} {wr_total:>6.1f}%")

        if trades_df.empty:
            print("\nNo trades executed!")
            return

        print("\n" + "=" * 85)
        print("OVERALL STATISTICS")
        print("=" * 85)

        total = len(trades_df)
        wins_df = trades_df[trades_df["pnl"] > 0]
        losses_df = trades_df[trades_df["pnl"] <= 0]
        wc = len(wins_df)
        lc = len(losses_df)
        wr = (wc / total * 100)

        print(f"Total Trades: {total}")
        print(f"Win Rate: {wr:.1f}%")
        print(f"Long: {len(trades_df[trades_df['side']=='long'])} | Short: {len(trades_df[trades_df['side']=='short'])}")
        print(f"Avg Win: ${wins_df['pnl'].mean():+.2f} | Avg Loss: ${losses_df['pnl'].mean():+.2f}")
        print(f"Largest Win: ${wins_df['pnl'].max():+.2f} | Largest Loss: ${losses_df['pnl'].min():+.2f}")
        gp = wins_df["pnl"].sum()
        gl = losses_df["pnl"].sum()
        pf = abs(gp / gl) if gl != 0 else float("inf")
        print(f"Gross Profit: ${gp:+.2f} | Gross Loss: ${gl:+.2f}")
        print(f"Profit Factor: {pf:.2f}")

        # Exit reasons
        print("\nExit Reasons:")
        for reason, count in trades_df["reason"].value_counts().items():
            print(f"  {reason}: {count} ({count/total*100:.1f}%)")

        # Drawdown
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df["peak"] = equity_df["equity"].cummax()
            equity_df["dd"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"] * 100
            print(f"\nMax Drawdown: {equity_df['dd'].min():.2f}%")

        # Save CSV
        out = trades_df.copy()
        out["entry_time"] = out["entry_time"].astype(str)
        out["exit_time"] = out["exit_time"].astype(str)
        out.to_csv("backtest_improved_trades.csv", index=False)
        print(f"\nSaved: backtest_improved_trades.csv")

        return trades_df

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 85)
    print("  BTC Global Elite Scalper V6 - IMPROVED Daily Backtest")
    print("  Filters: ADX, RSI | Trail Direction + STC + EMA200")
    print("=" * 85)

    df = fetch_data()
    if df is None:
        return

    print(f"\nCalculating indicators...")
    df = calculate_all_indicators(df)

    print(f"  Signals where close > trail: {(df['close'] > df['ut_trail']).sum()}")
    print(f"  Signals where close < trail: {(df['close'] < df['ut_trail']).sum()}")

    engine = BacktestEngine(df, initial_balance=INITIAL_BALANCE)
    engine.run()

if __name__ == "__main__":
    main()
