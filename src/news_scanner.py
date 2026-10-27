"""
Pre-Market News Scanner — fetches recent news for universe symbols via
Alpaca's news endpoint, scores them with Claude Haiku for likely
pre-market price impact, and emits buy candidates.

Output: list of {"symbol", "confidence", "reasoning", "headline"} dicts.
The runner (main.py) decides whether to act on them.
"""
import os
import json
import logging
from datetime import datetime, timedelta, timezone

import config

_log = logging.getLogger("trading_bot")

_NEWS_SYSTEM_PROMPT = """You are an equities news triage assistant for a pre-market trading bot.

You will receive a stock symbol and one or more news headlines from the last ~12 hours.
Your job: judge whether these headlines are likely to push the stock UP at pre-market open.

Respond ONLY with a single-line JSON object:
{"action": "BUY" or "SKIP", "confidence": <0-100 integer>, "reasoning": "<one concise sentence>"}

BUY criteria (high confidence 75+):
- Earnings beat / guidance raise
- FDA approval / clinical trial success
- Major product launch / chip/AI breakthrough
- Large contract / partnership / acquisition target
- Analyst upgrade by major firm with price target hike

SKIP (or low confidence):
- Rumor, opinion piece, generic market commentary
- Bearish/mixed news, lawsuits, downgrades, leadership departures
- Old/stale news already priced in
- Vague PR fluff

Be strict — false positives cost the bot real money. Reserve confidence 75+ for
clear hard-catalyst news. Keep reasoning under 20 words."""


def _get_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def fetch_news(api, symbols, hours_back=14):
    """
    Fetch news for `symbols` from the last `hours_back` hours via Alpaca news API.
    Returns dict: {symbol: [{"headline": str, "summary": str, "created_at": str}, ...]}
    """
    if not symbols:
        return {}

    start = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    by_symbol = {s: [] for s in symbols}

    # Alpaca SDK accepts comma-separated symbols, max 50 per call
    batch_size = 50
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            items = api.get_news(
                symbol=",".join(batch),
                start=start,
                limit=50,
            )
            for item in items:
                headline = getattr(item, "headline", "") or ""
                summary = getattr(item, "summary", "") or ""
                created = str(getattr(item, "created_at", ""))
                item_syms = getattr(item, "symbols", []) or []
                for sym in item_syms:
                    if sym in by_symbol:
                        by_symbol[sym].append({
                            "headline": headline,
                            "summary": summary[:300],
                            "created_at": created,
                        })
        except Exception as e:
            _log.warning(f"News fetch failed for batch starting {batch[0]}: {e}")

    n = sum(len(v) for v in by_symbol.values())
    syms_with_news = sum(1 for v in by_symbol.values() if v)
    _log.info(f"News: pulled {n} headlines across {syms_with_news}/{len(symbols)} symbols")
    return by_symbol


def score_symbol(symbol, headlines):
    """Ask Claude Haiku to score a symbol's news for pre-market BUY potential."""
    if not headlines:
        return None

    headlines_text = "\n".join(
        f"- {h['headline']}" + (f" ({h['summary'][:150]})" if h.get("summary") else "")
        for h in headlines[:5]
    )
    user_msg = f"Symbol: {symbol}\nHeadlines:\n{headlines_text}"

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=160,
            system=[{
                "type": "text",
                "text": _NEWS_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        decision = json.loads(raw)
        decision["symbol"] = symbol
        decision["headline"] = headlines[0]["headline"]
        return decision
    except Exception as e:
        _log.warning(f"News scoring failed for {symbol}: {e}")
        return None


def scan(api, symbols):
    """
    Full scan: fetch news, score each symbol with news, return high-confidence
    BUY candidates sorted by confidence desc.
    """
    news_by_symbol = fetch_news(api, symbols, config.PREMARKET_NEWS_LOOKBACK_HOURS)
    candidates = []
    for sym, headlines in news_by_symbol.items():
        if not headlines:
            continue
        scored = score_symbol(sym, headlines)
        if not scored:
            continue
        _log.info(
            f"News score {sym}: {scored.get('action')} "
            f"conf={scored.get('confidence')} — {scored.get('reasoning', '')[:80]}"
        )
        if (scored.get("action") == "BUY" and
                int(scored.get("confidence", 0)) >= config.PREMARKET_MIN_CONFIDENCE):
            candidates.append(scored)

    candidates.sort(key=lambda c: -int(c.get("confidence", 0)))
    return candidates[:config.PREMARKET_MAX_ENTRIES]
