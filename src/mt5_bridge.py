"""MT5 Bridge — MetaTrader 5 connection, order dispatch, and Telegram notifications."""

import os
import sys
import logging
import urllib.parse
import urllib.request

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".env"
    )
    load_dotenv(_ENV_PATH)
except ImportError:
    # python-dotenv not installed; falls back to system environment variables.
    pass

# ── Telegram ──────────────────────────────────────────────────────
TG_TOKEN   = os.getenv("TG_TOKEN",   "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
    handlers= [
        logging.StreamHandler(),
        logging.FileHandler("vmc_bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("MT5_Bridge")

if not TG_TOKEN or not TG_CHAT_ID:
    log.warning(
        "TG_TOKEN / TG_CHAT_ID not configured — "
        "copy .env.example to .env and fill in the values. "
        "Telegram notifications are disabled."
    )

def tg_send(msg: str) -> None:
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        params = urllib.parse.urlencode(
            {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        )
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage?{params}"
        urllib.request.urlopen(url, timeout=5)
    except Exception as e:
        log.warning(f"Telegram: {e}")

# ── Import MT5 ────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    log.warning("MetaTrader5 not installed — running in simulation mode.")
    class _MT5Dummy:
        ORDER_TYPE_BUY     = 0
        ORDER_TYPE_SELL    = 1
        ORDER_TIME_GTC     = 1
        ORDER_FILLING_IOC  = 1
        TRADE_ACTION_DEAL  = 1
        TRADE_RETCODE_DONE = 10009
        def __getattr__(self, _): return None
    mt5 = _MT5Dummy()


# ══════════════════════════════════════════════════════════════════
# SYMBOLS
# ══════════════════════════════════════════════════════════════════

SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
    "USDCAD", "USDCHF", "EURGBP", "EURJPY",
    "XAUUSD", "BTCUSD",
]


# ══════════════════════════════════════════════════════════════════
# MT5 BRIDGE
# ══════════════════════════════════════════════════════════════════

_MAGIC    = 20240101
_SLIPPAGE = 10

class MT5Bridge:

    def __init__(self):
        self._ok = False

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            log.warning("MetaTrader5 not installed — simulation mode active.")
            return False
        if not mt5.initialize():
            err = mt5.last_error()
            log.error(f"Cannot connect to MT5 ({err[0]}: {err[1]}).\n"
                      "  → Make sure MetaTrader 5 is open and logged in.")
            return False
        info = mt5.account_info()
        if info is None:
            log.error("MT5 initialized but no active account found.")
            mt5.shutdown()
            return False
        self._ok = True
        log.info(f"✅ MT5  account={info.login}  server={info.server}  "
                 f"balance={info.balance:.2f} {info.currency}")
        return True

    def disconnect(self):
        if MT5_AVAILABLE and self._ok:
            mt5.shutdown()
            self._ok = False

    def _digits(self, symbol: str) -> int:
        info = mt5.symbol_info(symbol) if MT5_AVAILABLE else None
        return info.digits if info else 5

    def _point(self, symbol: str) -> float:
        info = mt5.symbol_info(symbol) if MT5_AVAILABLE else None
        return info.point if info else 0.00001

    def _positions(self, symbol: str) -> list:
        if not MT5_AVAILABLE or not self._ok:
            return []
        return [p for p in (mt5.positions_get(symbol=symbol) or [])
                if p.magic == _MAGIC]

    def has_long(self, symbol: str) -> bool:
        return any(p.type == mt5.ORDER_TYPE_BUY  for p in self._positions(symbol))

    def has_short(self, symbol: str) -> bool:
        return any(p.type == mt5.ORDER_TYPE_SELL for p in self._positions(symbol))

    def close_position(self, pos) -> bool:
        if not MT5_AVAILABLE or not self._ok:
            return True
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        ct    = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        res   = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
            "volume": pos.volume, "type": ct, "position": pos.ticket,
            "price": price, "deviation": _SLIPPAGE, "magic": _MAGIC,
            "comment": "TV close", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        ok = res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'✅' if ok else '❌'} Close ticket={pos.ticket}  P&L={pos.profit:.2f}")
        return ok

    def close_all_longs(self, symbol: str):
        for p in self._positions(symbol):
            if p.type == mt5.ORDER_TYPE_BUY:
                self.close_position(p)

    def close_all_shorts(self, symbol: str):
        for p in self._positions(symbol):
            if p.type == mt5.ORDER_TYPE_SELL:
                self.close_position(p)

    def _pending_orders(self, symbol: str) -> list:
        if not MT5_AVAILABLE or not self._ok:
            return []
        return [o for o in (mt5.orders_get(symbol=symbol) or [])
                if o.magic == _MAGIC]

    def has_pending_buy(self, symbol: str) -> bool:
        return any(o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
                   for o in self._pending_orders(symbol))

    def has_pending_sell(self, symbol: str) -> bool:
        return any(o.type in (mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP)
                   for o in self._pending_orders(symbol))

    def send_pending_order(self, symbol: str, order_type: int,
                           price: float, lot: float = 0.01,
                           sl: float = 0.0, tp: float = 0.0,
                           comment: str = "") -> bool:
        _labels = {
            mt5.ORDER_TYPE_BUY_LIMIT:  "BUY_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP:   "BUY_STOP",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_SELL_STOP:  "SELL_STOP",
        }
        label = _labels.get(order_type, "PENDING")
        if not MT5_AVAILABLE or not self._ok:
            log.info(f"[SIM] {label} {lot}lot {symbol}@{price}  SL={sl}  TP={tp}")
            return True
        dig = self._digits(symbol)
        res = mt5.order_send({
            "action"      : mt5.TRADE_ACTION_PENDING,
            "symbol"      : symbol,
            "volume"      : lot,
            "type"        : order_type,
            "price"       : price,
            "sl"          : sl,
            "tp"          : tp,
            "magic"       : _MAGIC,
            "comment"     : f"TV {comment}",
            "type_time"   : mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        })
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"✅ {label} {symbol}  ticket={res.order}  entry={price:.{dig}f}  SL={sl:.{dig}f}  lot={lot}")
            return res.order
        log.error(f"❌ {symbol} {label} retcode={res.retcode}  {res.comment}")
        return False

    def send_order(self, symbol: str, order_type: int,
                   lot: float = 0.01, sl: float = 0.0,
                   tp: float = 0.0, comment: str = "") -> bool:
        label = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
        if not MT5_AVAILABLE or not self._ok:
            log.info(f"[SIM] {label} {lot}lot {symbol}  SL={sl}  TP={tp}")
            return True
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        dig   = self._digits(symbol)
        res   = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": lot, "type": order_type, "price": price,
            "sl": sl, "tp": tp, "deviation": _SLIPPAGE, "magic": _MAGIC,
            "comment": f"TV {comment}", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"✅ {label} {symbol}  ticket={res.order}  price={price:.{dig}f}  SL={sl:.{dig}f}  lot={lot}")
            tg_send(f"📡 <b>{label} {symbol}</b>\nTicket: {res.order}\nPrice: {price:.{dig}f}\nSL: {sl:.{dig}f}\nLot: {lot}")
            return res.order
        log.error(f"❌ {symbol} {label} retcode={res.retcode}  {res.comment}")
        return False
