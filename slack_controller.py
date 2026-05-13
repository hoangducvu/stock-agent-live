"""
Slack Controller — start/stop/monitor the trading bot from Slack.

Commands:
  !start            — launch the trading bot
  !stop             — gracefully shut it down
  !status           — check if it's running
  !buy SYMBOL       — place a test market buy ($10 max, paper safe)
  !help             — show commands
  Anything else     — ask the Claude AI about the bot (what it's doing, why it trades, etc.)
"""
import os
import re
import sys
import json
import subprocess
import threading
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Load .env ─────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

SLACK_BOT_TOKEN  = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN  = os.getenv("SLACK_APP_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALPACA_KEY       = os.getenv("APCA_API_KEY_ID", "")
ALPACA_SECRET    = os.getenv("APCA_API_SECRET_KEY", "")
TRADING_MODE     = os.getenv("TRADING_MODE", "paper")

if not SLACK_BOT_TOKEN or SLACK_BOT_TOKEN == "YOUR_SLACK_BOT_TOKEN":
    print("[FATAL] SLACK_BOT_TOKEN not set in .env")
    sys.exit(1)
if not SLACK_APP_TOKEN or SLACK_APP_TOKEN == "YOUR_SLACK_APP_TOKEN":
    print("[FATAL] SLACK_APP_TOKEN not set in .env")
    sys.exit(1)

# ── App ───────────────────────────────────────────────────────────────────────
app = App(token=SLACK_BOT_TOKEN)

# ── State ─────────────────────────────────────────────────────────────────────
_bot_process: "subprocess.Popen | None" = None
_bot_lock = threading.Lock()

_BASE_DIR = Path(__file__).parent
_STATE_FILE = _BASE_DIR / "data" / "bot_state.json"
_LOG_FILE   = _BASE_DIR / "logs"

_KEYWORDS = [
    "BUY", "SELL", "EXIT", "ENTRY", "FILLED", "HALT", "ERROR", "FATAL",
    "KILL SWITCH", "Portfolio Value", "P&L", "Day trade", "PDT",
    "SHUTDOWN", "STARTING UP", "Scheduler started", "exited unexpectedly",
    "STARTUP VALIDATION FAILED", "Cannot connect",
]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip(line: str) -> str:
    return _ANSI.sub("", line).strip()


def _is_important(line: str) -> bool:
    upper = line.upper()
    return any(kw.upper() in upper for kw in _KEYWORDS)


def _stream(process: subprocess.Popen, channel: str):
    try:
        for raw in process.stdout:
            line = _strip(raw)
            if line and _is_important(line):
                try:
                    app.client.chat_postMessage(channel=channel, text=f"`{line}`")
                except Exception:
                    pass
    except Exception:
        pass


def _watch(process: subprocess.Popen, channel: str):
    process.wait()
    code = process.returncode
    if code not in (0, -15):
        try:
            app.client.chat_postMessage(
                channel=channel,
                text=f":warning: Bot exited unexpectedly (code {code}). Use `!start` to restart.",
            )
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_bot_state() -> dict | None:
    """Read the live bot state written by main.py."""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _read_recent_logs(n: int = 30) -> str:
    """Return the last n lines from today's log file, stripped of ANSI."""
    try:
        import glob as _glob
        files = sorted(_glob.glob(str(_LOG_FILE / "trading_*.log")))
        if not files:
            return ""
        with open(files[-1]) as f:
            lines = f.readlines()
        tail = lines[-n:] if len(lines) >= n else lines
        return "".join(_ANSI.sub("", l) for l in tail)
    except Exception:
        return ""


def _build_system_prompt(state: dict | None) -> str:
    parts = [
        "You are the AI assistant for a live stock trading bot. "
        "Your job is to explain in plain English what the bot is doing, "
        "which stocks it bought or is watching, why it chose each strategy, "
        "and what is happening behind the scenes. "
        "Be conversational, clear, and give real numbers from the data."
    ]

    if state:
        parts.append(f"\n\n## Current Bot State (as of {state.get('timestamp', 'unknown')})")
        parts.append(f"- Running: {state.get('running', False)}")
        parts.append(f"- Portfolio value: ${state.get('portfolio_value', 0):,.2f}")
        parts.append(f"- Buying power: ${state.get('buying_power', 0):,.2f}")
        parts.append(f"- Daily P&L: ${state.get('daily_pnl', 0):+.2f}")
        parts.append(f"- PDT day trades used: {state.get('pdt_count', 0)}/{state.get('pdt_limit', 3)}")
        parts.append(f"- Halted: {state.get('halted', False)}")

        positions = state.get("open_positions", [])
        if positions:
            parts.append(f"\n## Open Positions ({len(positions)})")
            for p in positions:
                parts.append(
                    f"  - {p['symbol']} via {p['strategy']}: "
                    f"{p['qty']} shares @ ${p['entry_price']:.2f} entry, "
                    f"current ${p.get('current_price', 0):.2f}, "
                    f"unrealized P&L ${p.get('unrealized_pnl', 0):+.2f}, "
                    f"stop ${p['stop_loss']:.2f}"
                    + (f", target ${p['take_profit']:.2f}" if p.get('take_profit') else "")
                )
        else:
            parts.append("\n## Open Positions: none")

        trades = state.get("trades_today", [])
        if trades:
            parts.append(f"\n## Completed Trades Today ({len(trades)})")
            for t in trades:
                parts.append(
                    f"  - {t['symbol']} ({t['strategy']}): "
                    f"bought ${t['entry_price']:.2f}, sold ${t['exit_price']:.2f}, "
                    f"P&L ${t['pnl']:+.2f} ({t['pnl_pct']*100:+.2f}%), "
                    f"exit reason: {t['exit_reason']}"
                )
        else:
            parts.append("\n## Completed Trades Today: none")

        strats = state.get("strategies", {})
        if strats:
            parts.append("\n## Strategies the bot uses")
            for name, desc in strats.items():
                parts.append(f"  - {name}: {desc}")

        universe = state.get("stock_universe", [])
        if universe:
            parts.append(f"\n## Stock universe being scanned: {', '.join(universe)}")
    else:
        parts.append(
            "\n\nNote: The bot state file is not available right now. "
            "This usually means the bot is not running. "
            "Tell the user they can start it with `!start`."
        )

    return "\n".join(parts)


def _ask_claude(user_question: str, state: dict | None, recent_logs: str) -> str:
    """Send the user's question to Claude with full bot context."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        return (
            ":warning: `ANTHROPIC_API_KEY` is not set in `.env`. "
            "Add your key from console.anthropic.com to enable AI chat."
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system = _build_system_prompt(state)
        if recent_logs:
            system += f"\n\n## Recent Log Output (last 30 lines)\n```\n{recent_logs}\n```"

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_question}],
        )
        return message.content[0].text

    except Exception as e:
        return f":x: Claude AI error: {e}"


# ── Commands ──────────────────────────────────────────────────────────────────

@app.message("!start")
def cmd_start(message, say):
    global _bot_process
    channel = message["channel"]

    with _bot_lock:
        if _bot_process is not None and _bot_process.poll() is None:
            say(":white_check_mark: Bot is already running.")
            return

        try:
            _bot_process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(Path(__file__).parent),
            )
        except Exception as e:
            say(f":x: Failed to start bot: {e}")
            return

    say(f":rocket: Bot started (PID {_bot_process.pid}). Trade alerts will appear here.")

    threading.Thread(target=_stream, args=(_bot_process, channel), daemon=True).start()
    threading.Thread(target=_watch,  args=(_bot_process, channel), daemon=True).start()


@app.message("!stop")
def cmd_stop(message, say):
    global _bot_process
    with _bot_lock:
        if _bot_process is None or _bot_process.poll() is not None:
            say(":white_check_mark: Bot is not running.")
            return
        _bot_process.terminate()

    say(":octagonal_sign: Stop signal sent. Bot is shutting down gracefully.")


@app.message("!status")
def cmd_status(message, say):
    with _bot_lock:
        running = _bot_process is not None and _bot_process.poll() is None
        pid = _bot_process.pid if running else None
        code = _bot_process.returncode if (_bot_process and _bot_process.poll() is not None) else None

    state = _read_bot_state()

    if running:
        lines = [f":green_circle: Bot is *running* (PID {pid})."]
    elif _bot_process is None:
        lines = [":black_circle: Bot is *stopped*."]
    else:
        lines = [f":red_circle: Bot *exited* (code {code}). Use `!start` to restart."]

    if state:
        pnl = state.get("daily_pnl", 0)
        pnl_sign = "+" if pnl >= 0 else ""
        lines.append(
            f"  Portfolio: ${state.get('portfolio_value', 0):,.2f} | "
            f"Daily P&L: {pnl_sign}${pnl:.2f} | "
            f"PDT: {state.get('pdt_count', 0)}/{state.get('pdt_limit', 3)}"
        )
        positions = state.get("open_positions", [])
        if positions:
            lines.append(f"  Open positions: {', '.join(p['symbol'] for p in positions)}")
        else:
            lines.append("  Open positions: none")

    say("\n".join(lines))


@app.message(re.compile(r"^!buy\s+(\w+)", re.IGNORECASE))
def cmd_buy(message, say, context):
    """Force a small test market buy via Alpaca API directly."""
    symbol = context["matches"][0].upper()

    if not ALPACA_KEY or not ALPACA_SECRET:
        say(":x: Alpaca API keys not set in `.env`.")
        return

    base_url = (
        "https://paper-api.alpaca.markets"
        if TRADING_MODE != "live"
        else "https://api.alpaca.markets"
    )

    try:
        import alpaca_trade_api as tradeapi
        api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, base_url=base_url)

        # Get current price — get_latest_trade is reliable; 1Min bars via IEX return empty
        price = None
        try:
            trade = api.get_latest_trade(symbol)
            price = float(trade.price)
        except Exception:
            pass
        if price is None:
            try:
                bar = api.get_latest_bar(symbol)
                price = float(bar.c)
            except Exception:
                pass

        # $10 notional order (respects MAX_ORDER_VALUE)
        notional = 10.0
        qty = round(notional / price, 4) if price else None

        if not qty or qty <= 0:
            say(f":x: Could not get price for `{symbol}`.")
            return

        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side="buy",
            type="market",
            time_in_force="day",
        )

        mode_label = "PAPER" if TRADING_MODE != "live" else "LIVE"
        say(
            f":white_check_mark: *[{mode_label}] Test buy submitted*\n"
            f"  Symbol: `{symbol}`\n"
            f"  Qty: `{qty}` shares (~${notional:.2f})\n"
            f"  Est. price: `${price:.2f}`\n"
            f"  Order ID: `{order.id}`\n"
            f"  Status: `{order.status}`"
        )

    except Exception as e:
        say(f":x: Order failed: `{e}`")


@app.message("!help")
def cmd_help(message, say):
    say(
        "*Stock Bot Commands*\n"
        "`!start`         — launch the trading bot\n"
        "`!stop`          — gracefully shut it down\n"
        "`!status`        — check if it's running + portfolio snapshot\n"
        "`!buy SYMBOL`    — place a test market buy (~$10, paper safe)\n"
        "`!help`          — show this message\n"
        "\n*AI Chat* — just type any question and I'll explain what the bot is doing:\n"
        "_Examples: \"what did you buy today?\", \"why did you pick NVDA?\", \"explain EMA_VWAP\"_"
    )


@app.event("message")
def cmd_ai_chat(event, say):
    """Catch all messages not handled by a !command and route to Claude AI."""
    text = (event.get("text") or "").strip()

    # Skip empty, commands, and bot/system messages
    if not text or text.startswith("!"):
        return
    if event.get("bot_id") or event.get("subtype"):
        return

    print(f"[AI] received: {text[:80]}")

    try:
        say(":thinking_face: Checking bot status...")
    except Exception as e:
        print(f"[AI] say() error: {e}")
        return

    try:
        state = _read_bot_state()
        recent_logs = _read_recent_logs(30)
        reply = _ask_claude(text, state, recent_logs)
        say(reply)
    except Exception as e:
        print(f"[AI] claude error: {e}")
        say(f":x: Error getting AI response: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Slack controller starting...")
    print("Listening for !start / !stop / !status / !buy / !help + AI chat")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
