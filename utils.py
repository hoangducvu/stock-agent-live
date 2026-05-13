"""
Utilities — color output, formatting helpers, timezone handling.
"""
from datetime import datetime
import pytz

ET = pytz.timezone("US/Eastern")


# ─── ANSI Color Helpers ──────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"
def magenta(s): return f"\033[95m{s}\033[0m"


# ─── Formatting ──────────────────────────────────────────────────────────────
def fmt_price(p):
    """Format price with dollar sign."""
    if p is None:
        return "N/A"
    return f"${p:,.2f}"


def fmt_pct(p):
    """Format percentage."""
    if p is None:
        return "N/A"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def fmt_pnl(v):
    """Format P&L with color."""
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    s = f"${sign}{v:,.2f}"
    return green(s) if v >= 0 else red(s)


def fmt_shares(qty):
    """Format share quantity (fractional)."""
    if qty is None:
        return "N/A"
    return f"{qty:.4f}"


def fmt_ts():
    """Current timestamp in ET."""
    return datetime.now(ET).strftime("%H:%M:%S ET")


def now_et():
    """Current datetime in Eastern Time."""
    return datetime.now(ET)


def banner(text, width=80):
    """Print a wide banner."""
    line = "=" * width
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


def separator():
    print("-" * 80)
