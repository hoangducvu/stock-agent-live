"""
Risk Manager — position sizing, daily loss tracking, drawdown halt,
order size validation. All checks MUST pass before any order.
"""
import os
import math
from decimal import Decimal, ROUND_DOWN
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from logger_setup import get_logger
import config
from utils import now_et, fmt_price, fmt_pct, red, yellow, bold


@dataclass
class LivePosition:
    """Track a live position with entry info for P&L calculation."""
    symbol: str
    side: str               # "long" only (shorts disabled for $100)
    entry_price: float
    qty: float              # fractional shares
    entry_time: str
    strategy: str
    stop_loss: float
    take_profit: float
    trail_activate: Optional[float] = None
    trail_stop_atr: Optional[float] = None
    high_water: Optional[float] = None   # for trailing stop
    entry_value: float = 0.0


@dataclass
class TradeRecord:
    """Completed trade for daily log."""
    symbol: str
    side: str
    strategy: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    entry_time: str
    exit_time: str
    exit_reason: str
    sec_fee: float = 0.0


class RiskManager:
    """Enforces all risk limits for the live trading bot."""

    def __init__(self, account_manager):
        self.acct = account_manager
        self.log = get_logger()

        # Daily tracking
        self._daily_start_value = None
        self._daily_pnl = 0.0
        self._daily_halted = False
        self._bot_halted = False
        self._today = now_et().strftime("%Y-%m-%d")

        # Trade log for end-of-day summary
        self.trades_today: List[TradeRecord] = []

        # Tracked positions (our records, supplementing Alpaca's)
        self.positions: Dict[str, LivePosition] = {}
        self.pending_symbols = set()

    def init_daily(self, portfolio_value: float):
        """Call at start of each trading day."""
        today = now_et().strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self._daily_pnl = 0.0
            self._daily_halted = False
            self.trades_today = []
        if self._daily_start_value is None or today != getattr(self, "_baseline_day", None):
            self._daily_start_value = portfolio_value
            self._baseline_day = today
        self._restore_daily()
        self._persist_daily()
        self.log.info(f"Daily start value: {fmt_price(self._daily_start_value)}")

    # ─── Pre-Trade Checks ────────────────────────────────────────────────

    def _restore_daily(self):
        path = os.environ.get('NEXLARA_RISK_STATE')
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                state = json.load(f)
            if state.get('day') == self._today:
                baseline = float(state['baseline'])
                if not math.isfinite(baseline) or baseline <= 0:
                    raise ValueError('Invalid risk baseline')
                self._daily_start_value = baseline
                self._daily_halted = self._daily_halted or bool(state['daily_halted'])
            self._bot_halted = self._bot_halted or bool(state['bot_halted'])
        except Exception as e:
            raise RuntimeError('Risk checkpoint invalid; review before restarting') from e

    def _persist_daily(self):
        path = os.environ.get('NEXLARA_RISK_STATE')
        if not path:
            return
        from pathlib import Path
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        with temporary.open('w') as f:
            json.dump(dict(day=self._today, baseline=self._daily_start_value,
                           daily_halted=self._daily_halted, bot_halted=self._bot_halted), f)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(target)

    def can_trade(self) -> tuple:
        try:
            return self._can_trade()
        finally:
            self._persist_daily()

    def _can_trade(self) -> tuple:
        """
        Master check: can we place a new trade?
        Returns (allowed: bool, reason: str)
        """
        if self._bot_halted:
            return False, "Bot is HALTED due to max drawdown"

        if self._daily_halted:
            return False, "Daily loss limit reached — no more trades today"

        # Check drawdown
        try:
            current_value = self.acct.get_portfolio_value()
            pos_count = self.acct.get_position_count() + len(self.pending_symbols-set(self.positions))
        except Exception:
            return False, "Broker risk data unavailable"
        if not math.isfinite(current_value) or current_value <= 0:
            return False, "Broker equity is invalid"
        if current_value <= config.HALT_THRESHOLD_VALUE:
            self._bot_halted = True
            msg = (
                f"DRAWDOWN HALT: Portfolio {fmt_price(current_value)} "
                f"<= {fmt_price(config.HALT_THRESHOLD_VALUE)}"
            )
            self.log.critical(msg)
            print(f"\n  {red(bold('*** BOT HALTED — MAX DRAWDOWN ***'))}")
            print(f"  {red(msg)}")
            print(f"  {red('Manual review required. Restart bot after review.')}\n")
            return False, msg

        # Check daily loss
        if self._daily_start_value:
            daily_loss = self._daily_start_value - current_value
            max_loss = self._daily_start_value * config.MAX_DAILY_LOSS_PCT
            if daily_loss >= max_loss:
                self._daily_halted = True
                msg = (
                    f"DAILY LOSS LIMIT: Lost {fmt_price(daily_loss)} "
                    f"(limit: {fmt_price(max_loss)})"
                )
                self.log.warning(msg)
                print(f"\n  {yellow(bold('*** DAILY LOSS LIMIT REACHED ***'))}")
                print(f"  {yellow(msg)}")
                print(f"  {yellow('No more trades today.')}\n")
                return False, msg

        # Check position count
        if pos_count >= config.MAX_CONCURRENT_POSITIONS:
            return False, f"Max positions reached ({pos_count}/{config.MAX_CONCURRENT_POSITIONS})"

        return True, "OK"

    def validate_order(self, symbol: str, price: float,
                       qty: float, strategy=None) -> tuple:
        """
        Validate a specific order before submission.
        Returns (allowed: bool, reason: str)
        """
        if not all(math.isfinite(v) and v > 0 for v in (price, qty)):
            return False, "Price and quantity must be finite and positive"
        if symbol in self.pending_symbols:
            return False, 'Broker already has a pending order for this symbol'
        allowed, reason = self.can_trade()
        if not allowed:
            return False, reason
        order_value = price * qty

        # Hard cap on order size
        if order_value > config.MAX_ORDER_VALUE:
            return False, (
                f"Order value {fmt_price(order_value)} exceeds max "
                f"{fmt_price(config.MAX_ORDER_VALUE)}"
            )

        # Check buying power
        bp = self.acct.get_buying_power()
        if order_value > bp:
            return False, (
                f"Insufficient buying power: need {fmt_price(order_value)}, "
                f"have {fmt_price(bp)}"
            )

        if config.ALLOCATION_MODE=='fill_slots' or os.getenv('NEXLARA_MANAGED_AI')=='true':
            try:
                state=self._allocation_state(strategy)
                if state['slots']<=0 or order_value>state['capacity']+1e-8:
                    return False,'Allocation or overnight margin capacity exhausted'
            except Exception:return False,'Fresh broker allocation data unavailable'

        # Check we don't already hold this symbol
        if symbol in self.positions:
            return False, f"Already holding {symbol}"

        return True, "OK"

    # ─── Position Sizing ─────────────────────────────────────────────────

    def _allocation_state(self,strategy):
        from allocation import allocation_capacity
        account=self.acct.get_account()
        if account is None:raise RuntimeError('Account unavailable')
        positions=self.acct.get_open_positions()
        orders=self.acct.api.list_orders(status='open',limit=500)
        if len(orders)>=500:raise RuntimeError('Open-order response may be truncated; reconcile before more entries')
        return allocation_capacity(account,positions,orders,strategy,config.MAX_CONCURRENT_POSITIONS,config.MAX_GROSS_EXPOSURE,config.BUYING_POWER_RESERVE_PCT)

    def calc_position_size(self, price: float, strategy=None) -> tuple:
        """
        Calculate position size in dollars and fractional shares.
        Returns (qty: float, dollar_amount: float)
        """
        if not math.isfinite(price) or price <= 0:
            return 0.0, 0.0
        portfolio_value = self.acct.get_portfolio_value()
        buying_power = self.acct.get_buying_power()
        basis = buying_power if os.environ.get('NEXLARA_SIZING_BASIS') == 'buying_power' else portfolio_value
        dollars = min(basis * config.MAX_POSITION_PCT, config.MAX_ORDER_VALUE, buying_power)
        if config.ALLOCATION_MODE=='fill_slots':
            from allocation import allocation_budget
            try:dollars=allocation_budget(self._allocation_state(strategy),config.MAX_ORDER_VALUE)
            except Exception:return 0.0,0.0
        if config.ALLOCATION_MODE!='fill_slots' and os.getenv('NEXLARA_MANAGED_AI')=='true':
            try:
                state=self._allocation_state(strategy)
                if state['slots']<=0:return 0.0,0.0
                dollars=min(dollars,state['capacity'])
            except Exception:return 0.0,0.0
        if config.POSITION_SIZE_MULTIPLIER!=1:
            try:
                state=self._allocation_state(strategy)
                if state['slots']<=0:return 0.0,0.0
                dollars=min(dollars*config.POSITION_SIZE_MULTIPLIER,state['capacity'],config.MAX_ORDER_VALUE)
            except Exception:return 0.0,0.0
        if not math.isfinite(dollars) or dollars <= 0:
            return 0.0, 0.0
        # Leave room for the limit-price offset and round DOWN to six decimals.
        limit_price = round(price * (1 + config.LIMIT_OFFSET_PCT), 2)
        if limit_price <= 0:
            return 0.0, 0.0
        qty = float((Decimal(str(dollars)) / Decimal(str(limit_price))).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN))
        return qty, qty * price

    # ─── Position Tracking ───────────────────────────────────────────────

    def record_entry(self, pos: LivePosition):
        """Record a new position entry."""
        self.positions[pos.symbol] = pos
        self.log.info(
            f"Position opened: {pos.symbol} {pos.side} "
            f"{pos.qty:.4f} shares @ {fmt_price(pos.entry_price)} "
            f"(SL: {fmt_price(pos.stop_loss)}, TP: {fmt_price(pos.take_profit)})"
        )

    def record_exit(self, symbol: str, exit_price: float,
                    exit_reason: str, filled_qty: Optional[float] = None) -> Optional[TradeRecord]:
        """Record a position exit and calculate P&L."""
        pos = self.positions.get(symbol)
        if pos is None:
            self.log.warning(f"No tracked position for {symbol} on exit")
            return None

        qty = pos.qty if filled_qty is None else filled_qty
        if not math.isfinite(qty) or qty <= 0 or qty > pos.qty + 1e-8:
            raise ValueError("Invalid exit fill quantity")
        qty = min(qty, pos.qty)
        direction = -1 if pos.side == "short" else 1
        pnl = direction * (exit_price - pos.entry_price) * qty
        pnl_pct = direction * (exit_price - pos.entry_price) / pos.entry_price * 100

        # SEC fee (on sells)
        sell_value = (pos.entry_price if pos.side == "short" else exit_price) * qty
        sec_fee = sell_value * config.SEC_FEE_RATE

        trade = TradeRecord(
            symbol=symbol,
            side=pos.side,
            strategy=pos.strategy,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            qty=qty,
            pnl=pnl - sec_fee,
            pnl_pct=pnl_pct,
            entry_time=pos.entry_time,
            exit_time=now_et().strftime("%Y-%m-%d %H:%M:%S"),
            exit_reason=exit_reason,
            sec_fee=sec_fee,
        )

        if qty >= pos.qty - 1e-8:
            self.positions.pop(symbol)
        else:
            pos.qty -= qty
            pos.entry_value = pos.entry_price * pos.qty
        self._daily_pnl += trade.pnl
        self.trades_today.append(trade)

        return trade

    def update_high_water(self, symbol: str, current_price: float):
        """Update trailing stop high-water mark."""
        pos = self.positions.get(symbol)
        if pos and pos.high_water is not None:
            if ((pos.side == "short" and current_price < pos.high_water) or
                    (pos.side != "short" and current_price > pos.high_water)):
                pos.high_water = current_price

    # ─── Risk Metrics ────────────────────────────────────────────────────

    def risk_per_trade(self, entry_price: float, stop_loss: float,
                       qty: float) -> tuple:
        """
        Calculate dollar risk and portfolio risk percentage.
        Returns (dollar_risk, pct_risk)
        """
        dollar_risk = abs(entry_price - stop_loss) * qty
        portfolio_value = self.acct.get_portfolio_value()
        pct_risk = (dollar_risk / portfolio_value * 100) if portfolio_value > 0 else 0
        return dollar_risk, pct_risk

    def get_daily_pnl(self):
        """Return today's realized P&L."""
        return self._daily_pnl

    def is_halted(self):
        """Check if bot is halted."""
        return self._bot_halted

    def is_daily_halted(self):
        """Check if daily trading is halted."""
        return self._daily_halted

    # ─── End of Day ──────────────────────────────────────────────────────

    def save_daily_log(self):
        """Save today's trades to a JSON log file."""
        if not self.trades_today:
            return

        os.makedirs(config.LOGS_DIR, exist_ok=True)
        today = now_et().strftime("%Y%m%d")
        path = os.path.join(config.LOGS_DIR, f"trades_{today}.json")

        records = [asdict(t) for t in self.trades_today]
        with open(path, "w") as f:
            json.dump(records, f, indent=2)
        self.log.info(f"Trade log saved to {path}")
