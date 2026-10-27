"""
Claude Layer — inserts Claude (Haiku) as a reasoning layer between the
signal engine and execution.  Every BUY signal and every discretionary
exit signal passes through here before an order is placed.

Hard exits (stop_loss, take_profit, time_stop, trailing_stop) bypass
this layer entirely — capital protection always executes unconditionally.

Returns a dict: {"action": "EXECUTE"|"SKIP", "confidence": 0-100, "reasoning": str}
Falls through to EXECUTE on any API or parsing error so the bot never
stalls waiting for Claude.
"""
import os
import json
import logging

_log = logging.getLogger("claude_layer")

# Lazy-init so import doesn't fail if anthropic isn't installed yet
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


_SYSTEM_PROMPT = """You are a disciplined algorithmic trading assistant embedded in a live trading bot.
Your job is to perform a final sanity check on trade signals before execution.

You will be given:
- The strategy generating the signal
- Current indicator values
- Portfolio context

Respond ONLY with a JSON object on a single line — no explanation outside the JSON:
{"action": "EXECUTE" or "SKIP", "confidence": <0-100 integer>, "reasoning": "<one concise sentence>"}

Rules:
- EXECUTE if the indicators are broadly consistent with the strategy's thesis.
- SKIP only if you see a clear red flag: conflicting trend, extreme overextension,
  or data that flatly contradicts the entry/exit signal.
- Default to EXECUTE when uncertain — false negatives (missed trades) hurt more than
  occasional false positives in a well-risk-managed system.
- Confidence 70-90 is normal. Reserve <50 for genuine concerns.
- Keep reasoning under 15 words."""


def _call_claude(user_msg: str) -> dict:
    """Call claude-haiku-4-5 with a cached system prompt. Returns decision dict."""
    client = _get_client()

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=128,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if Claude adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _fallback(reason: str = "") -> dict:
    return {"action": "EXECUTE", "confidence": 50, "reasoning": reason or "fallback: API error"}


# ─── Entry Decision ──────────────────────────────────────────────────────────

def ask_entry(strategy: str, symbol: str, indicators: dict, portfolio: dict) -> dict:
    """
    Ask Claude whether to execute a BUY signal.

    indicators: output of strategy.entry_details()
    portfolio:  {"portfolio_value", "buying_power", "open_positions", "pdt_count"}
    """
    try:
        ind_lines = "\n".join(f"  {k}: {v}" for k, v in indicators.items())
        port_lines = (
            f"  portfolio_value: ${portfolio.get('portfolio_value', 0):,.0f}\n"
            f"  buying_power: ${portfolio.get('buying_power', 0):,.0f}\n"
            f"  open_positions: {portfolio.get('open_positions', 0)}\n"
            f"  pdt_used: {portfolio.get('pdt_count', 0)}/3"
        )

        user_msg = (
            f"ENTRY CHECK — {strategy} on {symbol}\n\n"
            f"Indicators:\n{ind_lines}\n\n"
            f"Portfolio:\n{port_lines}\n\n"
            f"Signal engine says BUY. Should we execute?"
        )

        result = _call_claude(user_msg)
        # Normalise action
        result["action"] = "EXECUTE" if str(result.get("action", "")).upper() == "EXECUTE" else "SKIP"
        return result

    except Exception as e:
        _log.debug(f"Claude entry check failed for {symbol}: {e}")
        return _fallback()


# ─── Exit Decision ───────────────────────────────────────────────────────────

def ask_exit(strategy: str, symbol: str, reason: str, indicators: dict, position: dict) -> dict:
    """
    Ask Claude whether to execute a discretionary EXIT signal.

    reason:     the exit reason from the strategy (e.g. "signal_exit", "rsi_exit")
    indicators: latest indicator row values
    position:   {"entry_price", "current_price", "qty", "unrealized_pnl_pct"}
    """
    try:
        ind_lines = "\n".join(f"  {k}: {v}" for k, v in indicators.items())
        pos_lines = (
            f"  entry_price: ${position.get('entry_price', 0):.2f}\n"
            f"  current_price: ${position.get('current_price', 0):.2f}\n"
            f"  unrealized_pnl: {position.get('unrealized_pnl_pct', 0)*100:+.2f}%\n"
            f"  qty: {position.get('qty', 0)}"
        )

        user_msg = (
            f"EXIT CHECK — {strategy} on {symbol}\n\n"
            f"Exit signal: {reason}\n\n"
            f"Current indicators:\n{ind_lines}\n\n"
            f"Position:\n{pos_lines}\n\n"
            f"Signal engine says EXIT ({reason}). Should we execute?"
        )

        result = _call_claude(user_msg)
        result["action"] = "EXECUTE" if str(result.get("action", "")).upper() == "EXECUTE" else "SKIP"
        return result

    except Exception as e:
        _log.debug(f"Claude exit check failed for {symbol}: {e}")
        return _fallback()
