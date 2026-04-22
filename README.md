# Crypto Bot — TradingView → MetaTrader 5 Bridge

Automated trading system for MetaTrader 5 that bridges TradingView alerts to live order execution. Continuously scans multiple FX and crypto symbols using a multi-EMA + RSI + ATR strategy, and optionally executes orders from Pine Script alerts via an authenticated webhook.

---

## Architecture

```
TradingView ──https──▶ ngrok ──▶ tv-webhook (Docker :5000)
                                       │ POST /execute
                                       ▼
                              mt5_executor.py (Windows host :5001)
                                       │
                                       ▼
                                  MetaTrader 5 ──▶ Telegram
```

`precision_sniper.py` runs independently of the webhook pipeline — it scans symbols on a configurable interval and sends orders directly to MT5.

---

## Features

- Continuous scanner across 10 symbols (FX majors + XAUUSD + BTCUSD).
- `precision_sniper` strategy with 6 built-in presets (Scalping, Aggressive, Default, Conservative, Swing, Crypto).
- Dynamic SL/TP management based on ATR with three take-profit levels (1.5×, 2.5×, 4× risk).
- TradingView → MT5 webhook bridge authenticated with a shared secret.
- Telegram notifications on every entry and close.
- Fully Dockerized webhook + ngrok tunnel — no router configuration required.

---

## Requirements

| Dependency | Notes |
|---|---|
| Windows 10 / 11 | The official `MetaTrader5` Python library is Windows-only. |
| MetaTrader 5 | Demo or live account, logged in before running. |
| Python 3.11+ | |
| Docker Desktop | For the webhook container and ngrok tunnel. |
| Telegram bot | Create one via [@BotFather](https://t.me/BotFather). |
| ngrok account | Free tier is sufficient; grab your auth token from the [dashboard](https://dashboard.ngrok.com/get-started/your-authtoken). |

---

## Installation

```cmd
git clone https://github.com/<your-username>/crypto-bot.git
cd crypto-bot
pip install -r requirements.txt
```

---

## Configuration

Copy both environment templates and fill in real values:

```cmd
copy .env.example .env
copy docker\.env.example docker\.env
```

| File | Variable | Description |
|---|---|---|
| `.env` | `TG_TOKEN` | Telegram bot token from @BotFather. |
| `.env` | `TG_CHAT_ID` | Chat ID where notifications are delivered. |
| `.env` | `WEBHOOK_SECRET` | Shared secret between Pine Script and the webhook. |
| `docker/.env` | `NGROK_AUTHTOKEN` | Your ngrok authentication token. |
| `docker/.env` | `WEBHOOK_SECRET` | Must be the same value as in the root `.env`. |

When pasting `pine/tradingview_alert.pine` into TradingView, replace the `TU_WEBHOOK_SECRET` placeholder with your actual `WEBHOOK_SECRET` value. **Do not edit the file in the repo** — edit the copy you paste into TradingView.

---

## Usage

Open MetaTrader 5 and log in. Then, from the project root:

```cmd
bin\start_all.bat
```

The launcher will:

1. Start `mt5_executor.py` on `localhost:5001`.
2. Bring up the webhook container and ngrok tunnel via `docker-compose`.
3. Print the public ngrok URL. Paste it into TradingView → Alert → Webhook URL (append `/webhook`).

To run the `precision_sniper` scanner in parallel:

```cmd
python src\precision_sniper.py
```

To stop all services:

```cmd
bin\stop_all.bat
```

To retrieve the current webhook URL without restarting:

```cmd
bin\get_url.bat
```

---

## Strategy

`precision_sniper` combines three EMAs (fast / slow / trend) + RSI + ATR to compute a directional score. An order is opened when the score exceeds the preset threshold; SL is set at `ATR × sl_mult` and the three TPs scale proportionally from the risk unit.

| Preset | EMAs (fast / slow / trend) | RSI len | Min score | SL × ATR |
|---|---|---|---|---|
| Scalping | 5 / 13 / 34 | 8 | 4 | 0.8 |
| Aggressive | 8 / 18 / 50 | 11 | 3 | 1.2 |
| Default | 9 / 21 / 55 | 13 | 5 | 1.5 |
| Conservative | 12 / 26 / 89 | 14 | 7 | 2.0 |
| Swing | 13 / 34 / 89 | 21 | 6 | 2.5 |
| Crypto | 9 / 21 / 55 | 14 | 5 | 2.0 |

Change the active preset by editing the `PRESET` constant in [src/precision_sniper.py](src/precision_sniper.py).

---

## Project Structure

```
crypto-bot/
├── src/
│   ├── mt5_bridge.py           MT5 connection, order dispatch, Telegram notifications
│   └── precision_sniper.py     Strategy engine and scanner (entrypoint)
├── scripts/
│   ├── mt5_executor.py         Flask server on the Windows host (port 5001)
│   ├── report.py               Prints current signal table to stdout
│   └── backtest_week.py        ⚠ Pending refactor (see Known Issues)
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── tv_webhook.py           Flask server inside the container (port 5000)
├── pine/
│   └── tradingview_alert.pine
├── bin/
│   ├── start_all.bat
│   ├── stop_all.bat
│   └── get_url.bat
├── .env.example
├── requirements.txt
└── .gitignore
```

---

## Known Issues

- **`scripts/backtest_week.py`** — imports a `Warmachines2` module from an older monolithic version that no longer exists in this repo. Needs to be refactored to use `mt5_bridge` + `precision_sniper`.
- The logger writes `vmc_bot.log` in the current working directory. Point it to a `logs/` folder by updating the `FileHandler` path in [src/mt5_bridge.py](src/mt5_bridge.py).

---

## Security

No credentials are stored in the repository. All secrets are loaded from local `.env` files (covered by `.gitignore`). If a credential is ever exposed, rotate it immediately:

- **Telegram** — create a new bot with @BotFather.
- **ngrok** — regenerate the token in the dashboard.
- **`WEBHOOK_SECRET`** — update the value in both `.env` files and in the TradingView alert.

---

## Disclaimer

This software is provided for educational purposes only. Trading leveraged instruments carries significant risk of capital loss. Always test on a demo account before connecting to a live account. The author assumes no responsibility for any financial outcomes resulting from the use of this software.

---

## License

No license specified.
