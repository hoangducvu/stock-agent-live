"""
Account Manager — Alpaca account checks, PDT day-trade tracking,
position queries, and startup validation.
"""
import json
import os
from datetime import datetime, timedelta
from collections import deque
from logger_setup import get_logger
import config
from utils import now_et, fmt_price, green, red, yellow, bold

PDT_LOG_FILE = os.path.join(config.DATA_DIR, "pdt_day_trades.json")


class AccountManager:
    """Manages Alpaca account state, PDT tracking, and position queries."""

    def __init__(self, api):
        """
        Args:
            api: alpaca_trade_api.REST instance
        """
        self.api = api
        self.log = get_logger()
        # Day trade log: list of {"symbol": str, "date": "YYYY-MM-DD"}
        self._day_trades = self._load_pdt_log()

    # ─── Account Info ────────────────────────────────────────────────────

    def get_account(self):
        """Fetch current account info from Alpaca."""
        try:
            return self.api.get_account()
        except Exception as e:
            self.log.error(f"Failed to fetch account: {e}")
            return None

    def get_portfolio_value(self):
        """Current portfolio value (equity)."""
        acct = self.get_account()
        if acct:
            return float(acct.equity)
        return 0.0

    def get_buying_power(self):
        """Available buying power."""
        acct = self.get_account()
        if acct:
            return float(acct.buying_power)
        return 0.0

    def get_open_positions(self):
        """Return list of open positions from Alpaca."""
        try:
            return self.api.list_positions()
        except Exception as e:
            self.log.error(f"Failed to fetch positions: {e}")
            return []

    def get_position_count(self):
        """Number of currently open positions."""
        return len(self.get_open_positions())

    def get_position(self, symbol):
        """Get a specific position, or None if not held."""
        try:
            return self.api.get_position(symbol)
        except Exception:
            return None

    # ─── Startup Validation ──────────────────────────────────────────────

    def validate_startup(self, trading_mode="paper"):
        """
        Run all startup checks. Returns (ok: bool, messages: list[str]).
        """
        messages = []
        ok = True
        self._trading_mode = trading_mode
        acct = self.get_account()
        if acct is None:
            return False, ["Cannot connect to Alpaca API"]

        # Account status
        status = acct.status
        if status != "ACTIVE":
            messages.append(f"Account status is {status}, not ACTIVE")
            ok = False

        # Sanity check: balance too high (only for LIVE mode)
        equity = float(acct.equity)
        if trading_mode == "live" and equity > config.SANITY_MAX_BALANCE:
            messages.append(
                f"Account balance {fmt_price(equity)} exceeds "
                f"{fmt_price(config.SANITY_MAX_BALANCE)}. "
                "This bot is configured for $100. Please verify."
            )
            ok = False

        # Check if account is restricted
        if getattr(acct, "trading_blocked", False):
            messages.append("Trading is blocked on this account")
            ok = False

        if getattr(acct, "account_blocked", False):
            messages.append("Account is blocked")
            ok = False

        return ok, messages

    def print_startup_info(self, kill_switch, close_on_shutdown, trading_mode="paper"):
        """Print the startup checklist banner."""
        acct = self.get_account()
        if acct is None:
            print(red("  Cannot connect to Alpaca. Check API keys."))
            return

        equity = float(acct.equity)
        buying_power = float(acct.buying_power)
        positions = self.get_open_positions()
        pdt_count = self.get_day_trade_count()

        # Check market status
        try:
            clock = self.api.get_clock()
            if clock.is_open:
                market_status = green("OPEN") + f" (closes at 4:00 PM ET)"
            else:
                market_status = yellow("CLOSED") + f" (next open: {clock.next_open})"
        except Exception:
            market_status = "UNKNOWN"

        # Next holiday
        next_holiday = self._get_next_holiday()

        ks = red("ON — SHUTTING DOWN") if kill_switch else green("OFF")

        if trading_mode == "live":
            mode_str = red(bold("LIVE (REAL MONEY)"))
        else:
            mode_str = yellow(bold("PAPER (SIMULATED)"))

        print(f"""
{'=' * 60}
  {bold('STOCK TRADING BOT — STARTING UP')}
{'=' * 60}
  Mode:            {mode_str}
  Account ID:      ****{str(getattr(acct, 'id', 'unknown'))[-4:]}
  Account Status:  {green(acct.status)}
  Portfolio Value: {fmt_price(equity)}
  Buying Power:    {fmt_price(buying_power)}
  Open Positions:  {len(positions)}
  Day Trades Used: {pdt_count}/{config.PDT_MAX_DAY_TRADES} (rolling 5-day)
  Kill Switch:     {ks}
  Close on Stop:   {'YES' if close_on_shutdown else 'NO'}
  Max Order Size:  {fmt_price(config.MAX_ORDER_VALUE)}
  Max Daily Loss:  {fmt_price(equity * config.MAX_DAILY_LOSS_PCT)}
  Halt Threshold:  {fmt_price(config.HALT_THRESHOLD_VALUE)}
  Market Status:   {market_status}
  Next Holiday:    {next_holiday}
{'=' * 60}""")

        # Strategy mode
        if pdt_count >= config.PDT_MAX_DAY_TRADES:
            print(f"  Strategy Mode:   {yellow('SWING ONLY')} (PDT limit reached)")
        else:
            print(f"  Strategy Mode:   {green('FULL')} (all 3 strategies active)")

        print(f"  Stock Universe:  {len(config.STOCK_UNIVERSE)} stocks "
              f"({len(config.TIER_1)} Tier 1, {len(config.TIER_2)} Tier 2)")
        print(f"  Scanning...")
        print(f"{'=' * 60}\n")

    # ─── PDT Tracking ────────────────────────────────────────────────────

    def record_day_trade(self, symbol):
        """Record a day trade (bought and sold same stock same day)."""
        today = now_et().strftime("%Y-%m-%d")
        self._day_trades.append({"symbol": symbol, "date": today})
        self._save_pdt_log()
        self.log.warning(
            f"PDT: Day trade recorded for {symbol}. "
            f"Count: {self.get_day_trade_count()}/{config.PDT_MAX_DAY_TRADES}"
        )

    def get_day_trade_count(self):
        """Count day trades in the rolling 5-business-day window."""
        cutoff = now_et() - timedelta(days=config.PDT_WINDOW_DAYS + 2)
        # Extra 2 days to account for weekends
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        count = sum(1 for t in self._day_trades if t["date"] >= cutoff_str)
        return count

    def can_day_trade(self):
        """Check if we can still make day trades."""
        return self.get_day_trade_count() < config.PDT_MAX_DAY_TRADES

    def _load_pdt_log(self):
        """Load PDT day trade log from disk."""
        os.makedirs(config.DATA_DIR, exist_ok=True)
        if os.path.exists(PDT_LOG_FILE):
            try:
                with open(PDT_LOG_FILE) as f:
                    data = json.load(f)
                # Prune old entries (older than 10 days)
                cutoff = (now_et() - timedelta(days=10)).strftime("%Y-%m-%d")
                return [t for t in data if t["date"] >= cutoff]
            except Exception:
                return []
        return []

    def _save_pdt_log(self):
        """Persist PDT day trade log to disk."""
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(PDT_LOG_FILE, "w") as f:
            json.dump(self._day_trades, f, indent=2)

    # ─── Market Calendar ─────────────────────────────────────────────────

    def is_trading_day(self):
        """Check if today is a trading day using Alpaca calendar."""
        try:
            today = now_et().strftime("%Y-%m-%d")
            cal = self.api.get_calendar(start=today, end=today)
            return len(cal) > 0
        except Exception as e:
            self.log.error(f"Failed to check calendar: {e}")
            # Default to weekday check
            return now_et().weekday() < 5

    def _get_next_holiday(self):
        """Find the next market holiday."""
        try:
            today = now_et()
            end = today + timedelta(days=90)
            cal = self.api.get_calendar(
                start=today.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d")
            )
            # Calendar returns trading days — find gaps
            if len(cal) < 2:
                return "N/A"

            for i in range(len(cal) - 1):
                d1 = datetime.strptime(str(cal[i].date), "%Y-%m-%d")
                d2 = datetime.strptime(str(cal[i + 1].date), "%Y-%m-%d")
                gap = (d2 - d1).days
                if gap > 3:  # More than a weekend gap = holiday
                    holiday_date = d1 + timedelta(days=1)
                    while holiday_date.weekday() >= 5:
                        holiday_date += timedelta(days=1)
                    return holiday_date.strftime("%B %d, %Y")
            return "None in next 90 days"
        except Exception:
            return "N/A"
