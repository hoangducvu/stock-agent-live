"""
Trade Explainer — generates analyst-style reasoning for every entry/exit.
"""
from logger_setup import get_logger
from utils import fmt_price, fmt_pct, fmt_shares, green, red, yellow, cyan, bold, dim
import config


def explain_entry(symbol: str, strategy: str, side: str, price: float,
                  qty: float, stop_loss: float, take_profit: float,
                  details: dict, risk_dollars: float, risk_pct: float,
                  pdt_count: int, buying_power: float,
                  confidence: str = "MEDIUM"):
    """
    Print and log a detailed analyst note for a trade entry.
    """
    log = get_logger()

    dollar_val = price * qty

    # Confidence color
    if confidence == "HIGH":
        conf_str = green(bold("HIGH"))
    elif confidence == "MEDIUM":
        conf_str = yellow("MEDIUM")
    else:
        conf_str = red("LOW")

    entry_str = green(f"LONG {symbol}") if side == "long" else red(f"SHORT {symbol}")

    lines = [
        "",
        f"  {'─' * 60}",
        f"  {bold('TRADE ENTRY')} | {entry_str} | {cyan(strategy)}",
        f"  {'─' * 60}",
        f"  Price:         {fmt_price(price)}",
        f"  Shares:        {fmt_shares(qty)}",
        f"  Position Size: {fmt_price(dollar_val)}",
        f"  Stop-Loss:     {fmt_price(stop_loss)}",
        f"  Take-Profit:   {fmt_price(take_profit) if take_profit else 'N/A'}",
        f"  Confidence:    {conf_str}",
        f"  Risk:          {fmt_price(risk_dollars)} ({fmt_pct(risk_pct)} of portfolio)",
        f"  PDT Count:     {pdt_count}/{config.PDT_MAX_DAY_TRADES}",
        f"  Buying Power:  {fmt_price(buying_power)} remaining",
    ]

    # Strategy-specific indicator details
    if strategy == "EMA_VWAP":
        lines.extend([
            f"  {'─' * 40}",
            f"  Indicators:",
            f"    EMA(9):   {_fv(details.get('ema9'))}",
            f"    EMA(21):  {_fv(details.get('ema21'))}",
            f"    EMA(55):  {_fv(details.get('ema55'))}",
            f"    VWAP:     {_fv(details.get('vwap'))}",
            f"    ATR(14):  {_fv(details.get('atr'))}",
            f"    Volume:   {_iv(details.get('volume'))} "
            f"(MA: {_iv(details.get('vol_ma'))})",
        ])
    elif strategy == "ORB":
        lines.extend([
            f"  {'─' * 40}",
            f"  Opening Range:",
            f"    High:     {_fv(details.get('orb_high'))}",
            f"    Low:      {_fv(details.get('orb_low'))}",
            f"    Width:    {_fv(details.get('orb_width'))}",
            f"    Volume:   {_iv(details.get('volume'))} "
            f"(MA: {_iv(details.get('vol_ma'))})",
        ])
    elif strategy == "RSI_BOUNCE":
        lines.extend([
            f"  {'─' * 40}",
            f"  Indicators:",
            f"    RSI(7):   {_fv(details.get('rsi7'))}",
            f"    BB Lower: {_fv(details.get('bb_lower'))}",
            f"    BB Mid:   {_fv(details.get('bb_mid'))}",
            f"    SMA(50):  {_fv(details.get('sma50'))}",
        ])

    lines.append(f"  {'─' * 60}")
    lines.append("")

    output = "\n".join(lines)
    print(output)
    log.info(output.replace("\033[", ""))  # strip ANSI for log file


def explain_exit(symbol: str, strategy: str, entry_price: float,
                 exit_price: float, qty: float, pnl: float,
                 pnl_pct: float, reason: str, hold_time: str = ""):
    """Print a concise exit summary."""
    log = get_logger()

    icon = green("W") if pnl >= 0 else red("L")
    pnl_str = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
    pct_str = green(fmt_pct(pnl_pct)) if pnl_pct >= 0 else red(fmt_pct(pnl_pct))

    line = (
        f"  {icon} EXIT {symbol} | {strategy} | "
        f"{fmt_price(entry_price)} → {fmt_price(exit_price)} | "
        f"P&L: {pnl_str} ({pct_str}) | {reason}"
    )
    if hold_time:
        line += f" | Held: {hold_time}"

    print(line)
    log.info(line.replace("\033[", ""))


def calc_confidence(strategy: str, details: dict) -> str:
    """Determine confidence level based on indicator strength."""
    if strategy == "EMA_VWAP":
        vol = details.get("volume", 0)
        vol_ma = details.get("vol_ma", 1)
        if vol_ma and vol_ma > 0:
            ratio = vol / vol_ma
            if ratio > 2.0:
                return "HIGH"
            elif ratio > 1.5:
                return "MEDIUM"
        return "LOW"

    elif strategy == "ORB":
        vol = details.get("volume", 0)
        vol_ma = details.get("vol_ma", 1)
        if vol_ma and vol_ma > 0:
            ratio = vol / vol_ma
            if ratio > 2.5:
                return "HIGH"
            elif ratio > 1.8:
                return "MEDIUM"
        return "LOW"

    elif strategy == "RSI_BOUNCE":
        rsi_val = details.get("rsi7", 50)
        if rsi_val and rsi_val < 18:
            return "HIGH"
        elif rsi_val and rsi_val < 22:
            return "MEDIUM"
        return "LOW"

    return "MEDIUM"


def _fv(val):
    """Format a float value."""
    if val is None:
        return "N/A"
    return f"{val:.2f}"


def _iv(val):
    """Format an integer value."""
    if val is None:
        return "N/A"
    return f"{int(val):,}"
