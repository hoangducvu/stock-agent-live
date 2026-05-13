"""
Strategy Selector — picks strategy per stock, enforces PDT override.

Priority:
  1. PDT override: if day trades >= 3, force RSI_BOUNCE only
  2. Gap > 1% → ORB
  3. ATR% > 2% → EMA_VWAP
  4. ATR% < 1.5% and range < 8% → RSI_BOUNCE
  5. Default → EMA_VWAP
"""
import config
from logger_setup import get_logger


def select_strategy(symbol: str, daily_row, gap_pct: float = 0.0,
                    can_day_trade: bool = True) -> tuple:
    """
    Select the best strategy for a symbol.

    Args:
        symbol: stock ticker
        daily_row: latest daily indicator row (pandas Series)
        gap_pct: overnight gap as decimal (e.g. 0.02 for 2%)
        can_day_trade: False if PDT limit reached

    Returns:
        (strategy_name: str, reason: str)
    """
    log = get_logger()

    # ── PDT Override ──
    if not can_day_trade:
        return "RSI_BOUNCE", "PDT limit reached — swing only (RSI Bounce)"

    # Need daily data for selection
    if daily_row is None:
        return "EMA_VWAP", "No daily data — defaulting to EMA+VWAP"

    price = daily_row.get("Close", 0)
    atr_val = daily_row.get("atr14", 0)

    if price == 0:
        return "EMA_VWAP", "No price data — defaulting to EMA+VWAP"

    atr_pct = atr_val / price if atr_val else 0

    # ── Gap Check → ORB ──
    if abs(gap_pct) > config.SEL_GAP_PCT:
        return "ORB", f"Gap {gap_pct*100:.2f}% > {config.SEL_GAP_PCT*100:.0f}% — ORB"

    # ── Volatility Check ──
    if atr_pct > config.SEL_ATR_PCT_HIGH:
        return "EMA_VWAP", f"ATR% {atr_pct*100:.2f}% > 2% — EMA+VWAP momentum"

    if atr_pct < config.SEL_ATR_PCT_LOW:
        # Also check range
        return "RSI_BOUNCE", f"ATR% {atr_pct*100:.2f}% < 1.5% — mean reversion"

    return "EMA_VWAP", f"Default (ATR%={atr_pct*100:.2f}%) — EMA+VWAP"


def get_applicable_strategies(symbol: str, daily_row, gap_pct: float = 0.0,
                              can_day_trade: bool = True) -> list:
    """
    Return list of all applicable strategies for a symbol today.
    Returns [(strategy_name, reason), ...]
    """
    if not can_day_trade:
        return [("RSI_BOUNCE", "PDT limit — swing only")]

    primary = select_strategy(symbol, daily_row, gap_pct, can_day_trade)
    results = [primary]

    # Always check RSI if not already primary
    if primary[0] != "RSI_BOUNCE":
        results.append(("RSI_BOUNCE", "Also checking RSI mean reversion"))

    # Check ORB if there's a notable gap and not already primary
    if primary[0] != "ORB" and abs(gap_pct) > config.SEL_GAP_PCT * 0.7:
        results.append(("ORB", f"Also checking ORB (gap {gap_pct*100:.2f}%)"))

    return results
