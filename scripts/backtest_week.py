"""
Backtest — previous week: 31 Mar – 4 Apr 2026
Simulates the exact bot logic with:
  - Dynamic SL: ATR(14) × 1.2
  - TP1 fixed, TP2 fixed, TP3 trailing (exits on opposite signal or VWAP→0)
  - EMA50 M5 filter
  - MFI filter
  - RSI filter
  - Per-candle anti re-entry guard
  - Immediate close on opposite signal

⚠️  BROKEN — NEEDS REFACTORING  ⚠️
────────────────────────────────────────────────────
This file imports "Warmachines2" (Config, ASSETS, compute_signals),
which no longer exists in the repo. It was part of a previous monolithic
version that has since been split into mt5_bridge.py + precision_sniper.py.

To restore, rewrite the imports as:
    from mt5_bridge      import SYMBOLS, MT5Bridge
    from precision_sniper import compute_signals, PRESETS, ...

Until then, this script raises ImportError on startup.
"""

import sys
import os

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, _SRC)

import pandas as pd
import numpy  as np
from datetime import datetime, timedelta

# TODO: rewrite import below to use mt5_bridge + precision_sniper
from Warmachines2 import (
    Config, ASSETS, MT5Bridge, compute_signals
)

# -- Date range ----------------------------------------------------
DATE_FROM = datetime(2026, 3, 31, 8, 0)
DATE_TO   = datetime(2026, 4,  4, 22, 0)

# -- Config matching the live bot ----------------------------------
cfg = Config()
cfg.BARS = 1000   # enough bars for 500 M5 candles + warmup

bridge = MT5Bridge(cfg)
bridge.connect()

results = []

for asset in ASSETS:
    symbol = asset.symbol

    df = bridge.get_ohlcv(symbol)
    if df is None or len(df) < 100:
        print(f"Skip {symbol}: insufficient data")
        continue

    df = compute_signals(df, cfg)

    mask = (df.index >= DATE_FROM) & (df.index <= DATE_TO)
    week = df[mask].copy()
    if len(week) < 10:
        print(f"Skip {symbol}: no bars in target week")
        continue

    # -- Trade simulation ------------------------------------------
    pt       = bridge.point(symbol)
    pip_mult = 10

    trades      = []
    open_pos    = []   # list of dicts: {dir, entry, sl, tp1, tp2, tp3_trail, be_done}
    last_entry  = None

    for i in range(1, len(week)):
        row      = week.iloc[i]
        prev     = week.iloc[i - 1]
        price    = row['close']
        candle_t = week.index[i]
        atr      = float(row['atr14']) if row['atr14'] > 0 else asset.sl_pips * pip_mult * pt

        rsi_ok_buy  = row['rsi'] < 55
        rsi_ok_sell = row['rsi'] > 45
        h1_buy      = True   # M5-only backtest — H1 filter not applicable on pre-filtered data
        h1_sell     = True

        buy  = (bool(row['signal_buy'])     and rsi_ok_buy)  or \
               (bool(row['signal_buy_div']) and rsi_ok_buy)  or \
               (bool(row['early_buy'])      and rsi_ok_buy)
        sell = (bool(row['signal_sell'])     and rsi_ok_sell) or \
               (bool(row['signal_sell_div']) and rsi_ok_sell) or \
               (bool(row['early_sell'])      and rsi_ok_sell)

        exit_long  = bool(row['exit_long'])
        exit_short = bool(row['exit_short'])

        sl_dist  = atr * 1.2
        tp1_dist = asset.tp1_pips * pip_mult * pt
        tp2_dist = asset.tp2_pips * pip_mult * pt
        tp3_dist = asset.tp3_pips * pip_mult * pt
        be_dist  = cfg.BE_PIPS    * pip_mult * pt

        new_open_pos = []
        for pos in open_pos:
            closed = False

            if pos['dir'] == 'BUY':
                profit = price - pos['entry']
                if pos['tp3_open']:
                    if exit_long or sell:
                        pips = round(profit / (pt * pip_mult), 1)
                        trades.append({'symbol': symbol, 'dir': 'BUY', 'result': 'TP3-EXIT',
                                       'pips': pips, 'time': candle_t})
                        closed = True
                if not closed and not pos['be_done'] and profit >= tp1_dist:
                    pos['sl'] = pos['entry'] + be_dist
                    pos['be_done'] = True
                if not closed and price <= pos['sl']:
                    pips = round((pos['sl'] - pos['entry']) / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'BUY', 'result': 'SL',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and pos['tp_level'] == 1 and price >= pos['tp1']:
                    pips = round(tp1_dist / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'BUY', 'result': 'TP1',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and pos['tp_level'] == 2 and price >= pos['tp2']:
                    pips = round(tp2_dist / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'BUY', 'result': 'TP2',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and sell:
                    pips = round(profit / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'BUY', 'result': 'REV',
                                   'pips': pips, 'time': candle_t})
                    closed = True

            else:  # SELL
                profit = pos['entry'] - price
                if pos['tp3_open']:
                    if exit_short or buy:
                        pips = round(profit / (pt * pip_mult), 1)
                        trades.append({'symbol': symbol, 'dir': 'SELL', 'result': 'TP3-EXIT',
                                       'pips': pips, 'time': candle_t})
                        closed = True
                if not closed and not pos['be_done'] and profit >= tp1_dist:
                    pos['sl'] = pos['entry'] - be_dist
                    pos['be_done'] = True
                if not closed and price >= pos['sl']:
                    pips = round((pos['entry'] - pos['sl']) / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'SELL', 'result': 'SL',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and pos['tp_level'] == 1 and price <= pos['tp1']:
                    pips = round(tp1_dist / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'SELL', 'result': 'TP1',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and pos['tp_level'] == 2 and price <= pos['tp2']:
                    pips = round(tp2_dist / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'SELL', 'result': 'TP2',
                                   'pips': pips, 'time': candle_t})
                    closed = True
                if not closed and not pos['tp3_open'] and buy:
                    pips = round(profit / (pt * pip_mult), 1)
                    trades.append({'symbol': symbol, 'dir': 'SELL', 'result': 'REV',
                                   'pips': pips, 'time': candle_t})
                    closed = True

            if not closed:
                new_open_pos.append(pos)

        open_pos = new_open_pos

        # Open new position — per-candle anti re-entry guard.
        has_long  = any(p['dir'] == 'BUY'  for p in open_pos)
        has_short = any(p['dir'] == 'SELL' for p in open_pos)

        if buy and not has_long and last_entry != candle_t:
            open_pos = [p for p in open_pos if p['dir'] != 'SELL']
            for tp_level, tp3_open in [(1, False), (2, False), (3, True)]:
                open_pos.append({
                    'dir': 'BUY', 'entry': price,
                    'sl':  price - sl_dist,
                    'tp1': price + tp1_dist,
                    'tp2': price + tp2_dist,
                    'tp_level': tp_level, 'tp3_open': tp3_open,
                    'be_done': False,
                })
            last_entry = candle_t

        elif sell and not has_short and last_entry != candle_t:
            open_pos = [p for p in open_pos if p['dir'] != 'BUY']
            for tp_level, tp3_open in [(1, False), (2, False), (3, True)]:
                open_pos.append({
                    'dir': 'SELL', 'entry': price,
                    'sl':  price + sl_dist,
                    'tp1': price - tp1_dist,
                    'tp2': price - tp2_dist,
                    'tp_level': tp_level, 'tp3_open': tp3_open,
                    'be_done': False,
                })
            last_entry = candle_t

    # Close all open positions at end of week.
    if open_pos and len(week) > 0:
        last_price = week.iloc[-1]['close']
        for pos in open_pos:
            if pos['dir'] == 'BUY':
                pips = round((last_price - pos['entry']) / (pt * pip_mult), 1)
            else:
                pips = round((pos['entry'] - last_price) / (pt * pip_mult), 1)
            trades.append({'symbol': symbol, 'dir': pos['dir'], 'result': 'OPEN',
                           'pips': pips, 'time': week.index[-1]})

    # -- Per-symbol statistics -------------------------------------
    tdf        = pd.DataFrame(trades) if trades else pd.DataFrame()
    sym_trades = tdf[tdf['symbol'] == symbol] if len(tdf) else pd.DataFrame()
    closed_t   = sym_trades[sym_trades['result'] != 'OPEN'] if len(sym_trades) else pd.DataFrame()

    n       = len(closed_t)
    wins    = len(closed_t[closed_t['pips'] > 0]) if n else 0
    losses  = n - wins
    wr      = round(wins / n * 100, 1) if n else 0
    tot_pip = round(closed_t['pips'].sum(), 1) if n else 0
    avg_win = round(closed_t[closed_t['pips'] > 0]['pips'].mean(), 1) if wins else 0
    avg_los = round(closed_t[closed_t['pips'] <= 0]['pips'].mean(), 1) if losses else 0

    results.append({
        'symbol'  : symbol,
        'trades'  : n,
        'wins'    : wins,
        'losses'  : losses,
        'WR%'     : wr,
        'tot_pips': tot_pip,
        'avg_win' : avg_win,
        'avg_loss': avg_los,
    })

bridge.disconnect()

# -- Print results -------------------------------------------------
print("\n" + "=" * 80)
print("  VMC Cipher B — Backtest 31 Mar – 4 Apr 2026  (M5, ATR SL, EMA50, MFI)")
print("=" * 80)
print(f"  {'Symbol':<10} {'Trades':>6} {'Win':>5} {'Loss':>5} {'WR%':>6} "
      f"{'Tot Pips':>10} {'Avg Win':>8} {'Avg Loss':>9}")
print("  " + "-" * 76)

tot_trades = tot_wins = tot_losses = tot_pips_all = 0
for r in sorted(results, key=lambda x: x['tot_pips'], reverse=True):
    print(f"  {r['symbol']:<10} {r['trades']:>6} {r['wins']:>5} {r['losses']:>5} "
          f"{r['WR%']:>6.1f} {r['tot_pips']:>10.1f} {r['avg_win']:>8.1f} {r['avg_loss']:>9.1f}")
    tot_trades   += r['trades']
    tot_wins     += r['wins']
    tot_losses   += r['losses']
    tot_pips_all += r['tot_pips']

print("  " + "-" * 76)
tot_wr = round(tot_wins / tot_trades * 100, 1) if tot_trades else 0
print(f"  {'TOTAL':<10} {tot_trades:>6} {tot_wins:>5} {tot_losses:>5} "
      f"{tot_wr:>6.1f} {tot_pips_all:>10.1f}")
print("=" * 80 + "\n")
