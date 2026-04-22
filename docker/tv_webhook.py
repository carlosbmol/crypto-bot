"""
TradingView Webhook Server — runs inside Docker
===============================================
Receives alerts from TradingView and forwards them to the MT5 Executor on the Windows host.
"""

import os
import logging
import requests
from flask import Flask, request, jsonify

WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET")
MT5_EXECUTOR_URL = os.environ.get("MT5_EXECUTOR_URL", "http://host.docker.internal:5001")

if not WEBHOOK_SECRET:
    raise RuntimeError(
        "WEBHOOK_SECRET is not set. Configure it in docker/.env "
        "(see docker/.env.example)."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
)
log = logging.getLogger("TV-Webhook")

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid json"}), 400

    log.info(f"Alert received: {data}")

    if data.get("secret") != WEBHOOK_SECRET:
        log.warning("Invalid secret — request rejected")
        return jsonify({"error": "unauthorized"}), 403

    symbol  = str(data.get("symbol", "")).upper().strip()
    action  = str(data.get("action", "")).upper().strip()
    comment = str(data.get("comment", "TV"))

    if not symbol or action not in ("BUY", "SELL", "CLOSE"):
        return jsonify({"error": "invalid symbol or action"}), 400

    try:
        resp = requests.post(
            f"{MT5_EXECUTOR_URL}/execute",
            json={"symbol": symbol, "action": action, "comment": comment},
            timeout=10,
        )
        result = resp.json()
        log.info(f"MT5 response: {result}")
        return jsonify(result), resp.status_code
    except requests.exceptions.ConnectionError:
        log.error("MT5 Executor unreachable — make sure mt5_executor.py is running on the Windows host")
        return jsonify({"error": "MT5 Executor unreachable"}), 503
    except Exception as e:
        log.error(f"Forwarding error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/status", methods=["GET"])
def status():
    try:
        resp = requests.get(f"{MT5_EXECUTOR_URL}/status", timeout=5)
        return jsonify({"webhook": "ok", "mt5_executor": resp.json()})
    except Exception:
        return jsonify({"webhook": "ok", "mt5_executor": "unreachable"}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  TradingView Webhook — Docker container")
    log.info(f"  MT5 Executor: {MT5_EXECUTOR_URL}")
    log.info(f"  Secret: {WEBHOOK_SECRET}")
    log.info("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
