import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timezone, timedelta
import os
import sys

# Import indicators from local project
import config
from indicators import calculate_all_indicators

def get_binance_data(symbol="BTCUSDT", interval="3m", limit=1000, start_time=None, end_time=None):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    if start_time:
        params["startTime"] = int(start_time * 1000)
    if end_time:
        params["endTime"] = int(end_time * 1000)
        
    for _ in range(3):
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 
                    'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                df['timestamp'] = df['timestamp'] / 1000.0
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            print(f"Error fetching data: {e}")
            time.sleep(2)
    return pd.DataFrame()

def fetch_historical_data(days=365):
    filename = f"btc_3m_{days}d.csv"
    if os.path.exists(filename):
        print(f"Loading data from {filename}...")
        df = pd.read_csv(filename)
        return df

    print(f"Downloading {days} days of 3m data from Binance...")
    end_time = time.time()
    start_time = end_time - (days * 24 * 60 * 60)
    
    all_data = []
    current_end = end_time
    
    while current_end > start_time:
        df = get_binance_data(end_time=current_end)
        if df.empty:
            break
        all_data.append(df)
        current_end = df['timestamp'].iloc[0] - 1
        print(f"Fetched up to {datetime.utcfromtimestamp(current_end).strftime('%Y-%m-%d')}")
        time.sleep(0.5)  # Rate limit
        
    if not all_data:
        return pd.DataFrame()
        
    full_df = pd.concat(all_data, ignore_index=True)
    full_df = full_df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)
    
    # Filter exact time window
    full_df = full_df[full_df['timestamp'] >= start_time]
    full_df.to_csv(filename, index=False)
    print(f"Saved {len(full_df)} rows to {filename}")
    return full_df

def run_backtest():
    df = fetch_historical_data(days=365)
    if df.empty:
        print("Failed to load data.")
        return

    print("Calculating indicators...")
    df = calculate_all_indicators(df)
    
    print("Starting simulation...")
    # Initial parameters
    capital = 1000.0
    start_capital = capital
    peak_capital = capital
    max_drawdown = 0.0
    
    trades = []
    open_trade = None
    
    # Constants
    PARTIAL_TP_PCT = config.PARTIAL_TP_PCT
    PARTIAL_TP_SIZE_RATIO = config.PARTIAL_TP_SIZE_RATIO
    BREAKEVEN_TRIGGER_PCT = config.BREAKEVEN_TRIGGER_PCT
    TRAILING_SL_ACTIVATION = config.TRAILING_SL_ACTIVATION
    TRAILING_SL_OFFSET_PCT = config.TRAILING_SL_OFFSET_PCT
    TIMEOUT_MINUTES = config.TIMEOUT_MINUTES
    STC_LONG = config.STC_LONG_THRESHOLD
    STC_SHORT = config.STC_SHORT_THRESHOLD
    LEVERAGE = config.LEVERAGE
    MARGIN_PCT = config.MARGIN_PERCENT
    
    last_trade_was_loss = False
    
    # For daily drawdown tracking
    current_day = None
    daily_start_capital = capital
    
    for i in range(config.EMA_PERIOD, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        timestamp = row['timestamp']
        date_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
        
        if current_day != date_str:
            current_day = date_str
            daily_start_capital = capital
            
        current_price = row['close']
        high = row['high']
        low = row['low']
        
        # Check Drawdown limit
        daily_dd = (daily_start_capital - capital) / daily_start_capital
        if daily_dd >= config.MAX_DAILY_DRAWDOWN:
            # Bot locked for the day, ignore signals
            if open_trade is None:
                continue
        
        if open_trade:
            # Manage open trade
            side = open_trade['side']
            entry_price = open_trade['entry_price']
            entry_time = open_trade['entry_time']
            size = open_trade['size']
            
            # Elapsed time
            elapsed_mins = (timestamp - entry_time) / 60.0
            
            # Calculate peak
            if side == 'buy':
                open_trade['peak_price'] = max(open_trade['peak_price'], high)
                profit_pct = (high - entry_price) / entry_price
                current_loss_pct = (low - entry_price) / entry_price
            else:
                open_trade['peak_price'] = min(open_trade['peak_price'], low)
                profit_pct = (entry_price - low) / entry_price
                current_loss_pct = (entry_price - high) / entry_price
                
            exit_reason = None
            exit_price = current_price
            
            # Liquidation check (approx 10% movement against position)
            if current_loss_pct <= -0.09:
                exit_reason = "Liquidation"
                if side == 'buy': exit_price = entry_price * (1 - 0.09)
                else: exit_price = entry_price * (1 + 0.09)
            
            # 1. Timeout Exit
            elif elapsed_mins >= TIMEOUT_MINUTES:
                exit_reason = "Timeout Exit"
                exit_price = current_price
                
            # 2. Breakeven SL
            elif open_trade['breakeven_active']:
                if side == 'buy' and low <= entry_price:
                    exit_reason = "Breakeven SL"
                    exit_price = entry_price
                elif side == 'sell' and high >= entry_price:
                    exit_reason = "Breakeven SL"
                    exit_price = entry_price
            
            # 3. Trailing SL
            elif open_trade['partial_tp_done']:
                peak = open_trade['peak_price']
                if side == 'buy':
                    sl_price = peak * (1 - TRAILING_SL_OFFSET_PCT)
                    if low <= sl_price:
                        exit_reason = "Trailing SL"
                        exit_price = sl_price
                else:
                    sl_price = peak * (1 + TRAILING_SL_OFFSET_PCT)
                    if high >= sl_price:
                        exit_reason = "Trailing SL"
                        exit_price = sl_price
                        
            # Check conditions during the candle
            if exit_reason is None:
                # Check Breakeven activation
                if profit_pct >= BREAKEVEN_TRIGGER_PCT and not open_trade['breakeven_active']:
                    open_trade['breakeven_active'] = True
                
                # Check Partial TP
                if profit_pct >= PARTIAL_TP_PCT and not open_trade['partial_tp_done']:
                    open_trade['partial_tp_done'] = True
                    # Record partial profit
                    pnl_pct = PARTIAL_TP_PCT
                    pnl_usd = (size * PARTIAL_TP_SIZE_RATIO) * pnl_pct * LEVERAGE
                    capital += pnl_usd
                    open_trade['realized_pnl'] += pnl_usd
                    open_trade['size'] *= (1 - PARTIAL_TP_SIZE_RATIO)
                    
            if exit_reason:
                # Close Trade
                if side == 'buy':
                    final_pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    final_pnl_pct = (entry_price - exit_price) / entry_price
                    
                final_pnl_usd = open_trade['size'] * final_pnl_pct * LEVERAGE
                capital += final_pnl_usd
                open_trade['realized_pnl'] += final_pnl_usd
                
                capital -= (open_trade['initial_size'] * 0.001) # Approx fees 0.1% per trade
                
                last_trade_was_loss = open_trade['realized_pnl'] < 0
                
                trades.append({
                    'entry_time': datetime.utcfromtimestamp(entry_time).strftime('%Y-%m-%d %H:%M'),
                    'exit_time': datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M'),
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'reason': exit_reason,
                    'pnl': open_trade['realized_pnl'],
                    'capital': capital
                })
                open_trade = None
                
                peak_capital = max(peak_capital, capital)
                drawdown = (peak_capital - capital) / peak_capital
                max_drawdown = max(max_drawdown, drawdown)
                
        else:
            # Evaluate new entry
            # Use prev_row for indicators to avoid lookahead bias
            ema200 = prev_row['ema200']
            stc = prev_row['stc']
            ut_signal = prev_row['ut_signal']
            close = prev_row['close']
            
            signal = None
            if close > ema200 and ut_signal == 'BUY' and stc > STC_LONG:
                signal = 'buy'
            elif close < ema200 and ut_signal == 'SELL' and stc < STC_SHORT:
                signal = 'sell'
                
            if signal:
                # Calculate size
                margin = capital * MARGIN_PCT
                notional = margin * LEVERAGE
                
                # Anti-martingale
                if last_trade_was_loss:
                    # Keep same size as base (we just use current capital margin)
                    pass 
                
                open_trade = {
                    'side': signal,
                    'entry_price': current_price,
                    'entry_time': timestamp,
                    'size': notional,
                    'initial_size': notional,
                    'peak_price': current_price,
                    'partial_tp_done': False,
                    'breakeven_active': False,
                    'realized_pnl': 0.0
                }

    # Output report
    if len(trades) > 0:
        trades_df = pd.DataFrame(trades)
        wins = len(trades_df[trades_df['pnl'] > 0])
        losses = len(trades_df[trades_df['pnl'] <= 0])
        win_rate = wins / len(trades) * 100
        total_pnl = capital - start_capital
        
        print("=======================================")
        print("          BACKTESTING REPORT           ")
        print("=======================================")
        print(f"Total Trades: {len(trades)}")
        print(f"Wins: {wins} | Losses: {losses}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Starting Capital: ${start_capital:.2f}")
        print(f"Final Capital: ${capital:.2f}")
        print(f"Total Net PnL: ${total_pnl:.2f} ({(total_pnl/start_capital)*100:.2f}%)")
        print(f"Max Drawdown: {max_drawdown*100:.2f}%")
        print("=======================================")
        
        trades_df.to_csv("backtest_trades.csv", index=False)
        print("Trade history saved to backtest_trades.csv")
        
        # Save to a nice markdown artifact
        report = f"""# BTC Global Elite Scalper V6 - 1 Year Backtest Report

**Symbol**: BTCUSDT  
**Timeframe**: 3m  
**Period**: 1 Year  

## Performance Summary
- **Total Trades**: {len(trades)}
- **Wins**: {wins}
- **Losses**: {losses}
- **Win Rate**: {win_rate:.2f}%
- **Starting Capital**: ${start_capital:.2f}
- **Final Capital**: ${capital:.2f}
- **Total Net PnL**: ${total_pnl:.2f} ({((total_pnl)/start_capital)*100:.2f}%)
- **Max Drawdown**: {max_drawdown*100:.2f}%

## Strategy Configuration
- **Leverage**: {LEVERAGE}x
- **Margin Per Trade**: {MARGIN_PCT*100}%
- **Indicators**: UT Bot, STC, EMA 200
- **Risk Management**: Partial TP ({PARTIAL_TP_PCT*100}%), Breakeven ({BREAKEVEN_TRIGGER_PCT*100}%), Trailing SL, 45m Timeout.
"""
        with open("backtest_report.md", "w") as f:
            f.write(report)
    else:
        print("No trades executed during the backtest period.")

if __name__ == "__main__":
    run_backtest()
