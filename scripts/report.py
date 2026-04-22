"""
Report — prints the current signal table to stdout (one row per symbol).

Run from the project root:
    python scripts/report.py
"""

import sys
import os

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, _SRC)

from precision_sniper import compute_signals, PRESET, ENTRY_ATR_MULT, BARS, TIMEFRAME
from mt5_bridge import SYMBOLS, MT5Bridge
import MetaTrader5 as mt5
import pandas as pd

bridge = MT5Bridge()
bridge.connect()

header = (
    f"{'SYMBOL':<10} {'PRICE':<12} {'ATR (pips)':<12} "
    f"{'ENTRY B':<12} {'ENTRY S':<12} "
    f"{'SL BUY':<12} {'SL SELL':<12} "
    f"{'RISK pips':<10} "
    f"{'TP1 BUY':<12} {'TP2 BUY':<12} {'TP3 BUY':<12} "
    f"{'TP1 SELL':<12} {'TP2 SELL':<12} {'TP3 SELL':<12} "
    f"SIGNAL"
)
print(header)
print("-" * len(header))

for sym in SYMBOLS:
    rates = mt5.copy_rates_from_pos(sym, TIMEFRAME, 0, BARS)
    if rates is None or len(rates) < 100:
        print(f"{sym:<10} NO DATA")
        continue

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    df = df[["open", "high", "low", "close", "volume"]]
    df = compute_signals(df, PRESET)
    last = df.iloc[-2]

    dig      = bridge._digits(sym)
    pt       = bridge._point(sym)
    atr      = float(last["atr"])
    atr_pips = round(atr / pt / 10, 1)
    offset   = round(atr_pips * ENTRY_ATR_MULT * 10 * pt, dig)
    close    = float(last["close"])

    sl_b  = round(float(last["sl_buy"]),   dig)
    sl_s  = round(float(last["sl_sell"]),  dig)
    tp1_b = round(float(last["tp1_buy"]),  dig)
    tp2_b = round(float(last["tp2_buy"]),  dig)
    tp3_b = round(float(last["tp3_buy"]),  dig)
    tp1_s = round(float(last["tp1_sell"]), dig)
    tp2_s = round(float(last["tp2_sell"]), dig)
    tp3_s = round(float(last["tp3_sell"]), dig)

    entry_b   = round(close - offset, dig)
    entry_s   = round(close + offset, dig)
    risk_pips = round((close - sl_b) / pt / 10, 1)

    sig = "BUY" if last["signal_buy"] else ("SELL" if last["signal_sell"] else "-")

    print(
        f"{sym:<10} {close:<12.{dig}f} {atr_pips:<12} "
        f"{entry_b:<12.{dig}f} {entry_s:<12.{dig}f} "
        f"{sl_b:<12.{dig}f} {sl_s:<12.{dig}f} "
        f"{risk_pips:<10} "
        f"{tp1_b:<12.{dig}f} {tp2_b:<12.{dig}f} {tp3_b:<12.{dig}f} "
        f"{tp1_s:<12.{dig}f} {tp2_s:<12.{dig}f} {tp3_s:<12.{dig}f} "
        f"{sig}"
    )

bridge.disconnect()
