"""
Strategy Selector — picks long AND short strategies per stock,
based on regime + universe scanner's bias hint.

Inputs from universe_scanner.bias():
  - "long_pullback"  → prefer RSI_BOUNCE long
  - "long_momentum"  → prefer EMA_VWAP long
  - "short_fade"     → prefer RSI_FADE short + EMA_VWAP_SHORT
  - "neutral"        → fall back to regime-based selection (old behavior)

Output: list of (strategy_name, reason) — caller iterates and asks each
strategy whether its `check_signal` fires.

The strategies themselves are the ultimate filter (volume, EMA cross,
extension guards), so being too liberal here just means more no-op
signal checks, not bad trades.
"""
import json
import os
from pathlib import Path

import config
from strategy_catalog import NAMES, IDS, SHORT_IDS
from logger_setup import get_logger


# Frontend IDs → bot internal strategy names
_ID_TO_NAME = {
    "ema_vwap": "EMA_VWAP",
    "ema_vwap_short": "EMA_VWAP_SHORT",
    "orb": "ORB",
    "rsi": "RSI_BOUNCE",
    "rsi_bounce": "RSI_BOUNCE",
    "rsi_fade": "RSI_FADE",
    "premarket_news": "PREMARKET_NEWS",
}


def load_disabled() -> set:
    """Read frontend-disabled strategy IDs, translate to internal names."""
    try:
        path = Path(__file__).parent / "data" / "disabled_strategies.json"
        if path.exists():
            ids = set(json.loads(path.read_text()))
            return {_ID_TO_NAME.get(i, i.upper()) for i in ids}
    except Exception:
        pass
    return set()


def filter_enabled(strategies):
    """Honor the selected strategy and disabled IDs on every selection path."""
    multi = os.environ.get('STRATEGIES')
    if multi is not None:
        ids = json.loads(multi)
        if not isinstance(ids, list) or not ids or any(i not in IDS for i in ids):
            raise ValueError('Invalid enabled strategies')
        allowed = {NAMES[i] for i in ids}
        return [(name, reason) for name, reason in strategies if name in allowed]
    selected = os.environ.get("STRATEGY", "").strip()
    if selected and selected not in _ID_TO_NAME:
        raise ValueError("Unsupported strategy: " + selected)
    disabled = load_disabled()
    return [(name, reason) for name, reason in strategies
            if name not in disabled and (not selected or name == _ID_TO_NAME[selected])]


def get_applicable_strategies(symbol: str, daily_row, gap_pct: float = 0.0,
                              can_day_trade: bool = True,
                              bias: str = "neutral",
                              shorts_enabled: bool = False) -> list:
    """
    Returns [(strategy_name, reason), ...] of strategies to evaluate.
    """
    log = get_logger()
    if os.environ.get('STRATEGIES') is not None:
        # Every checked strategy is evaluated; PDT and short permissions still apply.
        choices = []
        for item in json.loads(os.environ['STRATEGIES']):
            if item not in IDS: raise ValueError('Unsupported strategy: ' + str(item))
            if item in SHORT_IDS and not shorts_enabled: continue
            if not can_day_trade and item not in {'rsi', 'rsi_fade', 'trend_swing'}: continue
            choices.append((NAMES[item], 'Enabled in dashboard'))
        return filter_enabled(choices)
    disabled = load_disabled()

    # ── PDT override: swing only ──
    if not can_day_trade:
        out = [("RSI_BOUNCE", "Intraday broker eligibility unavailable — swing long")]
        if shorts_enabled:
            out.append(("RSI_FADE", "Intraday broker eligibility unavailable — swing short"))
        return filter_enabled(out)

    out = []

    # ── Bias-driven primary selection ──
    if bias == "long_pullback":
        out.append(("RSI_BOUNCE", "Top loser — oversold-bounce candidate"))
        out.append(("EMA_VWAP", "Also checking momentum recovery"))

    elif bias == "short_fade" and shorts_enabled:
        out.append(("RSI_FADE", "Top gainer — overbought-fade candidate"))
        out.append(("EMA_VWAP_SHORT", "Also checking momentum breakdown"))

    elif bias == "long_momentum":
        out.append(("EMA_VWAP", "Most-active — momentum candidate"))
        if abs(gap_pct) > config.SEL_GAP_PCT:
            out.append(("ORB", f"Gap {gap_pct*100:+.2f}% — also check ORB"))

    else:  # neutral — old regime-based logic
        if daily_row is None:
            out.append(("EMA_VWAP", "No daily data — default momentum"))
        else:
            price = daily_row.get("Close", 0)
            atr_val = daily_row.get("atr14", 0)
            atr_pct = (atr_val / price) if price else 0

            if abs(gap_pct) > config.SEL_GAP_PCT:
                out.append(("ORB", f"Gap {gap_pct*100:+.2f}% > {config.SEL_GAP_PCT*100:.0f}%"))
            if atr_pct > config.SEL_ATR_PCT_HIGH:
                out.append(("EMA_VWAP", f"ATR% {atr_pct*100:.2f}% high → momentum"))
            if atr_pct < config.SEL_ATR_PCT_LOW:
                out.append(("RSI_BOUNCE", f"ATR% {atr_pct*100:.2f}% low → mean reversion"))
            if not out:
                out.append(("EMA_VWAP", f"Default (ATR%={atr_pct*100:.2f}%)"))

        # Always also check RSI_BOUNCE and (if enabled) RSI_FADE on neutral
        names = {s[0] for s in out}
        if "RSI_BOUNCE" not in names:
            out.append(("RSI_BOUNCE", "Always check oversold bounce"))
        if shorts_enabled and "RSI_FADE" not in names:
            out.append(("RSI_FADE", "Always check overbought fade"))

    return filter_enabled(out)


# Back-compat shim for any caller still using the old signature
def select_strategy(symbol, daily_row, gap_pct=0.0, can_day_trade=True):
    apps = get_applicable_strategies(symbol, daily_row, gap_pct, can_day_trade)
    return apps[0] if apps else (None, "No enabled strategy")
