"""
MT5 Executor — runs on the Windows host (NOT inside Docker)
===========================================================
Receives trade commands from the webhook container and executes them on MetaTrader 5.

Run from the project root:
    python scripts/mt5_executor.py

Binds to localhost:5001 — not exposed externally.
"""

import sys
import os
import logging
from flask import Flask, request, jsonify

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, _SRC)
from mt5_bridge import SYMBOLS, MT5Bridge, tg_send

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mt5_executor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("MT5-Executor")

bridge = MT5Bridge()
app    = Flask(__name__)

def ensure_connected():
    if not bridge._ok:
        bridge.connect()
    return bridge._ok

@app.route("/execute", methods=["POST"])
def execute():
    data    = request.get_json(force=True)
    symbol  = data.get("symbol", "").upper()
    action  = data.get("action", "").upper()
    comment = data.get("comment", "TV")
    lot = float(data.get("lot", 0.01))
    sl  = float(data.get("sl",  0.0))
    tp1 = float(data.get("tp1", 0.0))
    tp2 = float(data.get("tp2", 0.0))
    tp3 = float(data.get("tp3", 0.0))

    if symbol not in SYMBOLS:
        return jsonify({"error": f"symbol {symbol} is not enabled"}), 400

    if not ensure_connected():
        return jsonify({"error": "MT5 not connected"}), 503

    if action == "BUY":
        if bridge.has_short(symbol):
            bridge.close_all_shorts(symbol)
        if not bridge.has_long(symbol):
            bridge.send_order(symbol, mt5.ORDER_TYPE_BUY, lot=lot, sl=sl, tp=tp1, comment=f"{comment} #1")
            bridge.send_order(symbol, mt5.ORDER_TYPE_BUY, lot=lot, sl=sl, tp=tp2, comment=f"{comment} #2")
            bridge.send_order(symbol, mt5.ORDER_TYPE_BUY, lot=lot, sl=sl, tp=tp3, comment=f"{comment} #3")
            return jsonify({"status": "BUY ×3 OK"})
        return jsonify({"status": "already long, skip"})

    elif action == "SELL":
        if bridge.has_long(symbol):
            bridge.close_all_longs(symbol)
        if not bridge.has_short(symbol):
            bridge.send_order(symbol, mt5.ORDER_TYPE_SELL, lot=lot, sl=sl, tp=tp1, comment=f"{comment} #1")
            bridge.send_order(symbol, mt5.ORDER_TYPE_SELL, lot=lot, sl=sl, tp=tp2, comment=f"{comment} #2")
            bridge.send_order(symbol, mt5.ORDER_TYPE_SELL, lot=lot, sl=sl, tp=tp3, comment=f"{comment} #3")
            return jsonify({"status": "SELL ×3 OK"})
        return jsonify({"status": "already short, skip"})

    elif action == "CLOSE":
        bridge.close_all_longs(symbol)
        bridge.close_all_shorts(symbol)
        return jsonify({"status": "CLOSE OK"})

    return jsonify({"error": "invalid action"}), 400

@app.route("/status", methods=["GET"])
def status():
    positions = []
    if bridge._ok and MT5_AVAILABLE:
        from mt5_bridge import _MAGIC
        pos = mt5.positions_get() or []
        positions = [
            {"symbol": p.symbol, "type": "BUY" if p.type == 0 else "SELL",
             "profit": round(p.profit, 2)}
            for p in pos if p.magic == _MAGIC
        ]
    return jsonify({"mt5_connected": bridge._ok, "positions": positions})

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  MT5 Executor — localhost:5001")
    log.info("=" * 50)
    bridge.connect()
    app.run(host="127.0.0.1", port=5001, debug=False)
