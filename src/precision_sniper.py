"""
Precision Sniper — Python Bot
==============================
Port of the Pine Script "Precision Sniper [WillyAlgoTrader]" logic.
Scans configured assets and opens MT5 orders with ATR-based SL/TP.

Run from the project root:
    python src/precision_sniper.py
"""

import sys
import os
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mt5_bridge import SYMBOLS, MT5Bridge, tg_send, _MAGIC

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

log = logging.getLogger("PrecisionSniper")

# ══════════════════════════════════════════════════════════════════
# PRESETS
# ══════════════════════════════════════════════════════════════════

PRESETS = {
    "Scalping":     dict(ema_fast=5,  ema_slow=13, ema_trend=34, rsi_len=8,  atr_len=10, min_score=4, sl_mult=0.8),
    "Aggressive":   dict(ema_fast=8,  ema_slow=18, ema_trend=50, rsi_len=11, atr_len=12, min_score=3, sl_mult=1.2),
    "Default":      dict(ema_fast=9,  ema_slow=21, ema_trend=55, rsi_len=13, atr_len=14, min_score=5, sl_mult=1.5),
    "Conservative": dict(ema_fast=12, ema_slow=26, ema_trend=89, rsi_len=14, atr_len=14, min_score=7, sl_mult=2.0),
    "Swing":        dict(ema_fast=13, ema_slow=34, ema_trend=89, rsi_len=21, atr_len=20, min_score=6, sl_mult=2.5),
    "Crypto":       dict(ema_fast=9,  ema_slow=21, ema_trend=55, rsi_len=14, atr_len=20, min_score=5, sl_mult=2.0),
}

PRESET       = "Default"     # options: Scalping / Aggressive / Default / Conservative / Swing / Crypto
LOT          = 0.10
TP1_MULT     = 1.5           # TP1 = risk × 1.5
TP2_MULT     = 2.5           # TP2 = risk × 2.5
TP3_MULT     = 4.0           # TP3 = risk × 4.0
SWING_BARS   = 10            # lookback for structural swing high/low
CHECK_SEC    = 1
TIMEFRAME    = mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15
BARS         = 300


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _rsi(s: pd.Series, n: int) -> pd.Series:
    d  = s.diff()
    ag = d.clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    al = (-d.clip(upper=0)).ewm(com=n - 1, min_periods=n).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def _macd(s: pd.Series):
    fast   = _ema(s, 12)
    slow   = _ema(s, 26)
    macd   = fast - slow
    signal = _ema(macd, 9)
    hist   = macd - signal
    return macd, signal, hist

def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low']  - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _adx(df: pd.DataFrame, n: int = 14):
    """Returns (adx, di_plus, di_minus)."""
    up   = df['high'].diff()
    down = -df['low'].diff()
    dm_plus  = up.where((up > down) & (up > 0), 0.0)
    dm_minus = down.where((down > up) & (down > 0), 0.0)
    atr_n    = _atr(df, n)
    di_plus  = 100 * _ema(dm_plus,  n) / atr_n.replace(0, np.nan)
    di_minus = 100 * _ema(dm_minus, n) / atr_n.replace(0, np.nan)
    dx       = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx      = _ema(dx, n)
    return adx, di_plus, di_minus

def _vwap_rolling(df: pd.DataFrame, n: int = 20) -> pd.Series:
    hlc3   = (df['high'] + df['low'] + df['close']) / 3
    vol    = df['volume'].replace(0, np.nan)
    return (hlc3 * vol).rolling(n).sum() / vol.rolling(n).sum()

def _grade(score: float) -> str:
    if score >= 8.0: return "A+"
    if score >= 6.5: return "A"
    if score >= 5.0: return "B"
    return "C"


# ══════════════════════════════════════════════════════════════════
# SIGNAL COMPUTATION
# ══════════════════════════════════════════════════════════════════

def compute_signals(df: pd.DataFrame, preset: str = "Default", sl_mult_override: float = None) -> pd.DataFrame:
    p = {**PRESETS.get(preset, PRESETS["Default"])}
    if sl_mult_override is not None:
        p['sl_mult'] = sl_mult_override
    df = df.copy()
    c  = df['close']

    df['ema_fast']  = _ema(c, p['ema_fast'])
    df['ema_slow']  = _ema(c, p['ema_slow'])
    df['ema_trend'] = _ema(c, p['ema_trend'])
    df['atr']       = _atr(df, p['atr_len'])
    df['rsi']       = _rsi(c, p['rsi_len'])

    df['macd'], df['macd_sig'], df['macd_hist'] = _macd(c)

    df['vol_sma']       = _sma(df['volume'], 20)
    df['vol_above_avg'] = df['volume'] > df['vol_sma'] * 1.2

    df['adx'], df['di_plus'], df['di_minus'] = _adx(df, 14)
    df['strong_trend'] = df['adx'] > 20

    df['vwap'] = _vwap_rolling(df, 20)

    df['swing_low']  = df['low'].rolling(SWING_BARS).min()
    df['swing_high'] = df['high'].rolling(SWING_BARS).max()

    # ── Bull score ─────────────────────────────────────────────────
    df['bull_score'] = (
        (df['ema_fast'] > df['ema_slow']).astype(float)          +  # +1
        (c > df['ema_trend']).astype(float)                       +  # +1
        ((df['rsi'] > 50) & (df['rsi'] < 75)).astype(float)      +  # +1
        (df['macd_hist'] > 0).astype(float)                       +  # +1
        (df['macd'] > df['macd_sig']).astype(float)               +  # +1
        (c > df['vwap']).astype(float)                            +  # +1
        df['vol_above_avg'].astype(float)                         +  # +1
        (df['strong_trend'] & (df['di_plus'] > df['di_minus'])).astype(float) +  # +1
        (c > df['ema_fast']).astype(float) * 0.5                     # +0.5
    )

    # ── Bear score ─────────────────────────────────────────────────
    df['bear_score'] = (
        (df['ema_fast'] < df['ema_slow']).astype(float)           +
        (c < df['ema_trend']).astype(float)                       +
        ((df['rsi'] < 50) & (df['rsi'] > 25)).astype(float)      +
        (df['macd_hist'] < 0).astype(float)                       +
        (df['macd'] < df['macd_sig']).astype(float)               +
        (c < df['vwap']).astype(float)                            +
        df['vol_above_avg'].astype(float)                         +
        (df['strong_trend'] & (df['di_minus'] > df['di_plus'])).astype(float) +
        (c < df['ema_fast']).astype(float) * 0.5
    )

    # ── EMA crossover — 3-candle lookback window ───────────────────
    _bull_raw = (df['ema_fast'].shift(1) < df['ema_slow'].shift(1)) & (df['ema_fast'] >= df['ema_slow'])
    _bear_raw = (df['ema_fast'].shift(1) > df['ema_slow'].shift(1)) & (df['ema_fast'] <= df['ema_slow'])
    ema_bull_cross = _bull_raw | _bull_raw.shift(1) | _bull_raw.shift(2)
    ema_bear_cross = _bear_raw | _bear_raw.shift(1) | _bear_raw.shift(2)

    bull_momentum = (c > df['ema_fast']) & (c > df['ema_slow'])
    bear_momentum = (c < df['ema_fast']) & (c < df['ema_slow'])

    # ── Entry signals (confirmed closed candle only) ───────────────
    min_score = p['min_score']
    df['signal_buy']  = (ema_bull_cross & bull_momentum &
                         (df['rsi'] < 75) & (df['bull_score'] >= min_score))
    df['signal_sell'] = (ema_bear_cross & bear_momentum &
                         (df['rsi'] > 25) & (df['bear_score'] >= min_score))

    # ── SL / TP ────────────────────────────────────────────────────
    sl_dist = df['atr'] * p['sl_mult']
    # Structural SL: below swing low for buys, above swing high for sells.
    # Use structural level only if it tightens the stop (closer to entry).
    sl_buy_atr     = c - sl_dist
    sl_sell_atr    = c + sl_dist
    sl_buy_struct  = df['swing_low']  - df['atr'] * 0.2
    sl_sell_struct = df['swing_high'] + df['atr'] * 0.2
    df['sl_buy']   = sl_buy_struct.where(sl_buy_struct  > sl_buy_atr,   sl_buy_atr)
    df['sl_sell']  = sl_sell_struct.where(sl_sell_struct < sl_sell_atr, sl_sell_atr)

    df['risk_buy']  = (c - df['sl_buy']).abs()
    df['risk_sell'] = (c - df['sl_sell']).abs()

    df['tp1_buy']  = c + df['risk_buy']  * TP1_MULT
    df['tp2_buy']  = c + df['risk_buy']  * TP2_MULT
    df['tp3_buy']  = c + df['risk_buy']  * TP3_MULT
    df['tp1_sell'] = c - df['risk_sell'] * TP1_MULT
    df['tp2_sell'] = c - df['risk_sell'] * TP2_MULT
    df['tp3_sell'] = c - df['risk_sell'] * TP3_MULT

    return df


# ══════════════════════════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════════════════════════

ENTRY_ATR_MULT = 0.1   # default ATR offset for pending entry price

# Per-symbol overrides: sl_mult and entry_atr_mult replace the preset values.
SYMBOL_OVERRIDES = {
    "XAUUSD": dict(sl_mult=2.0, entry_atr_mult=0.2, lot=0.02),
    "BTCUSD": dict(sl_mult=2.5, entry_atr_mult=0.3, lot=0.05),
}

class PrecisionSniperBot:

    def __init__(self):
        self.bridge          = MT5Bridge()
        self._last_signal    = {}   # symbol -> 'buy' | 'sell'
        self._last_bar_time  = {}   # symbol -> timestamp of last processed candle
        self._tp2            = {}   # ticket -> tp2 price
        self._be_done        = set()  # tickets already moved to breakeven
        self._open_tickets   = {}   # ticket -> {symbol, direction, entry}

    def _get_ohlcv(self, symbol: str) -> pd.DataFrame | None:
        if not MT5_AVAILABLE or not self.bridge._ok:
            return None
        rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, BARS)
        if rates is None or len(rates) < 100:
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'tick_volume': 'volume'}, inplace=True)
        return df[['open', 'high', 'low', 'close', 'volume']]

    def _process(self, symbol: str):
        df = self._get_ohlcv(symbol)
        if df is None:
            return

        ov      = SYMBOL_OVERRIDES.get(symbol, {})
        sl_mult = ov.get("sl_mult", None)
        e_mult  = ov.get("entry_atr_mult", ENTRY_ATR_MULT)
        lot     = ov.get("lot", LOT)

        df   = compute_signals(df, PRESET, sl_mult_override=sl_mult)
        last = df.iloc[-2]   # last CLOSED candle

        # Skip if this bar was already processed (anti re-entry guard).
        bar_time = df.index[-2]
        if self._last_bar_time.get(symbol) == bar_time:
            return
        self._last_bar_time[symbol] = bar_time

        dig        = self.bridge._digits(symbol)
        score_buy  = round(float(last['bull_score']), 1)
        score_sell = round(float(last['bear_score']), 1)

        pt        = self.bridge._point(symbol)
        atr_price = float(last['atr'])
        atr_pips  = atr_price / pt / 10
        offset    = round(atr_pips * e_mult * 10 * pt, dig)

        signal = (last['signal_buy']  and self._last_signal.get(symbol) != 'buy') or \
                 (last['signal_sell'] and self._last_signal.get(symbol) != 'sell')

        if signal:
            # Use the live tick as the entry reference instead of the candle close
            # to avoid placing pending orders that are immediately triggered.
            tick = mt5.symbol_info_tick(symbol) if MT5_AVAILABLE else None
            if tick is None:
                return
            sym_info = mt5.symbol_info(symbol) if MT5_AVAILABLE else None
            min_dist = (sym_info.trade_stops_level * pt) if sym_info else 0
            spread   = tick.ask - tick.bid
            # Effective offset must satisfy: ATR offset, broker stops_level, and
            # at least 2× the spread — brokers enforce this minimum distance.
            eff_offset = max(offset, min_dist + pt, spread * 2 + pt)

            entry_s = round(tick.ask + eff_offset, dig)   # Buy Stop  — above ask
            entry_b = round(tick.bid - eff_offset, dig)   # Sell Stop — below bid

            # Structural SL levels are fixed from the signal candle.
            sl_b = round(float(last['sl_buy']),  dig)
            sl_s = round(float(last['sl_sell']), dig)

            # TPs are computed from the real entry price, not the candle close,
            # so they are always on the correct side of the entry.
            risk_b = float(last['risk_buy'])
            risk_s = float(last['risk_sell'])
            tp1_b = round(entry_s + risk_b * TP1_MULT, dig)
            tp2_b = round(entry_s + risk_b * TP2_MULT, dig)
            tp3_b = round(entry_s + risk_b * TP3_MULT, dig)
            tp1_s = round(entry_b - risk_s * TP1_MULT, dig)
            tp2_s = round(entry_b - risk_s * TP2_MULT, dig)
            tp3_s = round(entry_b - risk_s * TP3_MULT, dig)

            grade  = _grade(max(score_buy, score_sell))
            placed = False

            # ── 3× Buy Stop ───────────────────────────────────────────
            if not self.bridge.has_long(symbol) and not self.bridge.has_pending_buy(symbol):
                b1 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_BUY_STOP,  price=entry_s, lot=lot, sl=sl_b, tp=tp1_b, comment=f"PS {grade} B#1")
                b2 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_BUY_STOP,  price=entry_s, lot=lot, sl=sl_b, tp=tp2_b, comment=f"PS {grade} B#2")
                b3 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_BUY_STOP,  price=entry_s, lot=lot, sl=sl_b, tp=tp3_b, comment=f"PS {grade} B#3")
                for t in [b1, b2, b3]:
                    if t and isinstance(t, int):
                        self._open_tickets[t] = {"symbol": symbol, "direction": "BUY", "entry": entry_s}
                if b3 and isinstance(b3, int):
                    self._tp2[b3] = {"tp1": tp1_b, "tp2": tp2_b}
                if b1 or b2 or b3:
                    placed = True

            # ── 3× Sell Stop ──────────────────────────────────────────
            if not self.bridge.has_short(symbol) and not self.bridge.has_pending_sell(symbol):
                s1 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_SELL_STOP, price=entry_b, lot=lot, sl=sl_s, tp=tp1_s, comment=f"PS {grade} S#1")
                s2 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_SELL_STOP, price=entry_b, lot=lot, sl=sl_s, tp=tp2_s, comment=f"PS {grade} S#2")
                s3 = self.bridge.send_pending_order(symbol, mt5.ORDER_TYPE_SELL_STOP, price=entry_b, lot=lot, sl=sl_s, tp=tp3_s, comment=f"PS {grade} S#3")
                for t in [s1, s2, s3]:
                    if t and isinstance(t, int):
                        self._open_tickets[t] = {"symbol": symbol, "direction": "SELL", "entry": entry_b}
                if s3 and isinstance(s3, int):
                    self._tp2[s3] = {"tp1": tp1_s, "tp2": tp2_s}
                if s1 or s2 or s3:
                    placed = True

            if placed:
                sig_label = 'buy' if last['signal_buy'] else 'sell'
                self._last_signal[symbol] = sig_label
                log.info(f"⚡ {symbol} [{grade}]  Buy Stop@{entry_s}  Sell Stop@{entry_b}  offset={round(eff_offset/pt/10,1)}pips")
                tg_send(
                    f"⚡ <b>SIGNAL {symbol}</b> [{grade}]\n"
                    f"🟢 Buy Stop:  {entry_s}  SL: {sl_b}  TP1: {tp1_b}  TP2: {tp2_b}  TP3: {tp3_b}\n"
                    f"🔴 Sell Stop: {entry_b}  SL: {sl_s}  TP1: {tp1_s}  TP2: {tp2_s}  TP3: {tp3_s}\n"
                    f"Offset: {round(eff_offset/pt/10,1)} pips"
                )

    def _sync_pending_to_positions(self):
        """Replaces pending-order tickets with live position tickets after fill."""
        if not MT5_AVAILABLE or not self.bridge._ok or not self._open_tickets:
            return
        positions = mt5.positions_get() or []
        for pos in positions:
            if pos.magic != _MAGIC:
                continue
            orig = pos.identifier   # equals the original pending order ticket
            if orig in self._open_tickets and pos.ticket != orig:
                info = self._open_tickets.pop(orig)
                self._open_tickets[pos.ticket] = info
                if orig in self._tp2:
                    self._tp2[pos.ticket] = self._tp2.pop(orig)
                if orig in self._be_done:
                    self._be_done.discard(orig)
                    self._be_done.add(pos.ticket)
                log.info(f"📋 {info['symbol']} pending {orig} → pos {pos.ticket}")

    def _manage_trailing(self):
        """Moves SL to TP1 once price reaches TP2 (applied to the third lot only)."""
        if not MT5_AVAILABLE or not self.bridge._ok:
            return
        positions = mt5.positions_get() or []
        for pos in positions:
            ticket = pos.ticket
            levels = self._tp2.get(ticket)
            if levels is None or ticket in self._be_done:
                continue
            tp1 = levels["tp1"]
            tp2 = levels["tp2"]
            dig  = self.bridge._digits(pos.symbol)
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue
            price  = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
            tp2_hit = (pos.type == mt5.ORDER_TYPE_BUY  and price >= tp2) or \
                      (pos.type == mt5.ORDER_TYPE_SELL and price <= tp2)
            if not tp2_hit:
                continue
            new_sl = round(tp1, dig)
            res = mt5.order_send({
                "action"  : mt5.TRADE_ACTION_SLTP,
                "symbol"  : pos.symbol,
                "position": ticket,
                "sl"      : new_sl,
                "tp"      : pos.tp,
            })
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                self._be_done.add(ticket)
                log.info(f"🔒 SL→TP1 {pos.symbol} ticket={ticket}  SL→{new_sl:.{dig}f}")
                tg_send(f"🔒 <b>SL moved to TP1 — {pos.symbol}</b>\nTP2 reached — SL now at {new_sl:.{dig}f}")
            # Purge stale tickets (positions that no longer exist).
        pending_tickets = {o.ticket for o in (mt5.orders_get() or [])}
        live_tickets    = {p.ticket for p in positions} | pending_tickets
        for t in list(self._tp2):
            if t not in live_tickets:
                self._tp2.pop(t, None)
                self._be_done.discard(t)

    def _cancel_opposite_pending(self):
        """Cancels opposing pending orders once a position is filled on that symbol."""
        if not MT5_AVAILABLE or not self.bridge._ok:
            return
        positions = mt5.positions_get() or []
        pending   = mt5.orders_get()   or []

        long_symbols  = {p.symbol for p in positions if p.type == mt5.ORDER_TYPE_BUY  and p.magic == _MAGIC}
        short_symbols = {p.symbol for p in positions if p.type == mt5.ORDER_TYPE_SELL and p.magic == _MAGIC}

        for o in pending:
            if o.magic != _MAGIC:
                continue
            is_sell_pending = o.type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP)
            is_buy_pending  = o.type in (mt5.ORDER_TYPE_BUY_LIMIT,  mt5.ORDER_TYPE_BUY_STOP)
            cancel = (
                (is_sell_pending and o.symbol in long_symbols)  or
                (is_buy_pending  and o.symbol in short_symbols)
            )
            if not cancel:
                continue
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_REMOVE,
                "order" : o.ticket,
            })
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                label = "Sell Stop" if is_sell_pending else "Buy Stop"
                log.info(f"🗑️ Cancelled {label} {o.symbol} ticket={o.ticket}")
                self._open_tickets.pop(o.ticket, None)
                self._tp2.pop(o.ticket, None)
                self._be_done.discard(o.ticket)

    def _check_closed(self):
        """Detects positions closed by TP/SL and sends a Telegram notification."""
        if not MT5_AVAILABLE or not self.bridge._ok or not self._open_tickets:
            return
        from datetime import datetime, timedelta

        positions  = mt5.positions_get() or []
        pending    = mt5.orders_get() or []
        active_now = {p.ticket for p in positions} | {o.ticket for o in pending}
        closed     = [t for t in list(self._open_tickets) if t not in active_now]

        for ticket in closed:
            info = self._open_tickets.pop(ticket, None)
            if info is None:
                continue

            # Query by position_id manually — the position= filter is bugged on some brokers.
            all_deals = mt5.history_deals_get(
                datetime.utcnow() - timedelta(hours=24),
                datetime.utcnow(),
            ) or []
            deals = [d for d in all_deals if d.position_id == ticket]
            if not deals:
                self._tp2.pop(ticket, None)
                self._be_done.discard(ticket)
                continue

            closing_deal = next((d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None)
            if closing_deal is None:
                self._tp2.pop(ticket, None)
                self._be_done.discard(ticket)
                continue

            symbol     = info['symbol']
            direction  = info['direction']
            profit     = sum(d.profit     for d in deals)
            commission = sum(d.commission for d in deals)
            swap       = sum(d.swap       for d in deals)
            net        = round(profit + commission + swap, 2)
            dig        = self.bridge._digits(symbol)

            if closing_deal.reason == mt5.DEAL_REASON_TP:
                emoji, label = "✅", "TAKE PROFIT"
            elif closing_deal.reason == mt5.DEAL_REASON_SL:
                emoji, label = "🛑", "STOP LOSS"
            else:
                emoji, label = "⚙️", "CLOSED"

            sign = "+" if net >= 0 else ""
            log.info(f"{emoji} {label} {symbol} ticket={ticket}  net={net:+.2f}")
            tg_send(
                f"{emoji} <b>{label} — {direction} {symbol}</b>\n"
                f"Ticket: {ticket}\n"
                f"Close price: {closing_deal.price:.{dig}f}\n"
                f"Profit: {sign}{round(profit, 2):.2f}\n"
                f"Commission: {round(commission, 2):.2f}  Swap: {round(swap, 2):.2f}\n"
                f"<b>Net: {sign}{net:.2f}</b>"
            )

            self._tp2.pop(ticket, None)
            self._be_done.discard(ticket)

    def start(self):
        log.info("=" * 60)
        log.info(f"  Precision Sniper Bot — preset: {PRESET}")
        log.info(f"  Symbols: {SYMBOLS}")
        log.info(f"  Lot: {LOT}  |  Scan interval: {CHECK_SEC}s")
        log.info(f"  Trailing: SL moves to TP1 when price reaches TP2")
        log.info("=" * 60)

        if not self.bridge.connect():
            log.warning("MT5 not connected.")

        while True:
            try:
                self._sync_pending_to_positions()
                self._manage_trailing()
                self._cancel_opposite_pending()
                self._check_closed()
                hora = datetime.now().hour
                if 8 <= hora < 20:
                    for symbol in SYMBOLS:
                        try:
                            self._process(symbol)
                        except Exception as e:
                            log.exception(f"{symbol}: {e}")
                else:
                    log.info("🌙 Outside trading hours (20:00–08:00) — no new orders.")
            except KeyboardInterrupt:
                log.info("Stopped.")
                self.bridge.disconnect()
                break
            except Exception as e:
                log.exception(f"Loop error: {e}")

            log.info(f"Waiting {CHECK_SEC}s…")
            time.sleep(CHECK_SEC)


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    PrecisionSniperBot().start()
