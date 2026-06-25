"""
Slack push notifications for live trade events.

Posts entry/exit fills and the end-of-day summary to a Slack channel via
chat.postMessage. Best-effort by design: any failure is swallowed so a Slack
problem can never block or crash trading. Active only when both SLACK_BOT_TOKEN
and SLACK_CHANNEL are present in the environment; otherwise every call is a
no-op. Env is read lazily on each call so a channel added after import is picked
up without reordering imports.
"""
import os

import requests

_API = "https://slack.com/api/chat.postMessage"


def _token() -> str:
    return os.getenv("SLACK_BOT_TOKEN", "").strip()


def _channel() -> str:
    return os.getenv("SLACK_CHANNEL", "").strip()


def enabled() -> bool:
    return bool(_token() and _channel())


def _post(text: str) -> None:
    if not enabled():
        return
    try:
        requests.post(
            _API,
            headers={"Authorization": f"Bearer {_token()}"},
            json={"channel": _channel(), "text": text, "unfurl_links": False},
            timeout=8,
        )
    except Exception:
        pass  # never let a notification failure affect trading


def notify_alert(title, detail="") -> None:
    """Post an operational alert (e.g. startup/auth failure) to Slack so problems
    surface loudly instead of dying silently in the log."""
    body = f":rotating_light: *{title}*"
    if detail:
        body += f"\n     {detail}"
    _post(body)


def notify_daily_plan(symbols, results=None) -> None:
    """Post the day's scanner-selected universe — the stocks the bot will trade
    today. `results` (optional) is the scanner's ranked rows with metrics; when
    present the top names are shown with their score so the message is scannable."""
    if not symbols:
        _post(":telescope: *Daily scan* — no stocks selected to trade today.")
        return

    header = (
        f":telescope: *Daily scan* — trading *{len(symbols)}* stocks today:\n"
        f"```{', '.join(symbols)}```"
    )

    detail = ""
    by_symbol = {r.get("symbol"): r for r in (results or []) if r.get("symbol")}
    top = [by_symbol[s] for s in symbols if s in by_symbol][:10]
    if top:
        lines = [
            f"  {i+1:>2}. {r['symbol']:<6} "
            f"score {r.get('score', 0):.2f} · ${r.get('price', 0):.2f} · "
            f"rvol {r.get('rel_volume', 0):.1f}x · gap {r.get('gap_pct', 0):+.1%}"
            for i, r in enumerate(top)
        ]
        more = f"\n  …and {len(symbols) - len(top)} more" if len(symbols) > len(top) else ""
        detail = "\n*Top picks:*\n```" + "\n".join(lines) + more + "```"

    _post(header + detail)


def notify_entry(symbol, strategy, qty, price, stop_loss, take_profit) -> None:
    tp = f" · tp ${take_profit:.2f}" if take_profit else ""
    _post(
        f":large_green_circle: *BUY {symbol}* x{qty} @ ${price:.2f}\n"
        f"     {strategy} · stop ${stop_loss:.2f}{tp}"
    )


def notify_exit(symbol, strategy, qty, exit_price, pnl, reason) -> None:
    emoji = ":red_circle:" if pnl < 0 else ":white_check_mark:"
    sign = "+" if pnl >= 0 else ""
    _post(
        f"{emoji} *SELL {symbol}* x{qty} @ ${exit_price:.2f} ({sign}{pnl:.2f})\n"
        f"     {strategy} · reason: {reason}"
    )


def notify_eod(trades, wins, losses, daily_pnl) -> None:
    sign = "+" if daily_pnl >= 0 else ""
    _post(
        f":bar_chart: *EOD summary* — {trades} trades, "
        f"{wins}W/{losses}L, {sign}${daily_pnl:.2f}"
    )
