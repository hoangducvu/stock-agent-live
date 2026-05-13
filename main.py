"""
Main — entry point for the live trading bot.
Handles startup, scheduling, the trading loop, and graceful shutdown.
"""
import os
import sys
import json
import signal
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import alpaca_trade_api as tradeapi
from apscheduler.schedulers.background import BackgroundScheduler

import config
from env_loader import load_env
from logger_setup import setup_logger, get_logger
from account_manager import AccountManager
from risk_manager import RiskManager, LivePosition
from order_manager import OrderManager
from data_feed import DataFeed
from utils import (
    now_et, fmt_price, fmt_pct, fmt_pnl, banner, separator,
    green, red, yellow, cyan, bold, dim, ET
)
import strategy_ema_vwap as s1
import strategy_orb as s2
import strategy_rsi as s3
import strategy_selector
import explainer


# ─── Global State ────────────────────────────────────────────────────────────
api = None
acct_mgr = None
risk_mgr = None
order_mgr = None
data_feed = None
scheduler = None
env_config = None
log = None
_shutting_down = False
_orb_computed = False


def main():
    global api, acct_mgr, risk_mgr, order_mgr, data_feed
    global scheduler, env_config, log, _orb_computed

    # ── Step 1: Setup logging ──
    log = setup_logger()

    # ── Step 2: Load environment ──
    env_config = load_env()

    # ── Step 3: Kill switch check ──
    if env_config["kill_switch"]:
        print(f"\n  {red(bold('*** KILL SWITCH IS ON ***'))}")
        print(f"  {red('Closing all positions and shutting down...')}\n")
        api = tradeapi.REST(
            env_config["api_key"],
            env_config["api_secret"],
            base_url=env_config["base_url"],
        )
        try:
            api.cancel_all_orders()
            api.close_all_positions()
            print(f"  {green('All positions closed. Bot shut down safely.')}")
        except Exception as e:
            print(f"  {red(f'Error during kill switch shutdown: {e}')}")
        sys.exit(0)

    # ── Step 4: Prevent duplicate instances via lockfile ──
    import atexit
    _lock_path = Path(__file__).parent / "data" / ".bot.lock"
    _lock_path.parent.mkdir(exist_ok=True)
    if _lock_path.exists():
        try:
            old_pid = int(_lock_path.read_text().strip())
            import psutil
            if psutil.pid_exists(old_pid):
                print(f"\n  {red(bold('*** ALREADY RUNNING (PID {old_pid}) ***'))}")
                print(f"  {red('Send !stop first, or the previous process will conflict.')}\n")
                sys.exit(1)
        except Exception:
            pass  # stale lock — proceed
    _lock_path.write_text(str(os.getpid()))
    atexit.register(lambda: _lock_path.unlink(missing_ok=True))

    # ── Step 5: Connect to Alpaca ──
    api = tradeapi.REST(
        env_config["api_key"],
        env_config["api_secret"],
        base_url=env_config["base_url"],
    )

    # ── Step 5: Initialize managers ──
    acct_mgr = AccountManager(api)
    risk_mgr = RiskManager(acct_mgr)
    order_mgr = OrderManager(api, risk_mgr, acct_mgr)
    data_feed = DataFeed(api)

    # ── Step 6: Startup validation ──
    mode = env_config["trading_mode"]
    ok, messages = acct_mgr.validate_startup(trading_mode=mode)
    if not ok:
        print(f"\n  {red(bold('*** STARTUP VALIDATION FAILED ***'))}")
        for msg in messages:
            print(f"  {red(msg)}")
        print(f"\n  {red('Bot will not start. Fix issues and try again.')}")
        sys.exit(1)

    # ── Step 7: Print startup info ──
    acct_mgr.print_startup_info(
        env_config["kill_switch"],
        env_config["close_on_shutdown"],
        trading_mode=mode,
    )

    # ── Step 8: Initialize daily risk tracking ──
    portfolio_value = acct_mgr.get_portfolio_value()
    risk_mgr.init_daily(portfolio_value)

    # ── Step 9: Register signal handlers for graceful shutdown ──
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ── Step 10: Check if market is open ──
    if not acct_mgr.is_trading_day():
        print(f"  {yellow('Today is not a trading day. Bot will wait.')}")

    # ── Step 11: Download historical data ──
    print(f"\n  {cyan('Downloading historical data...')}")
    data_feed.download_historical(config.STOCK_UNIVERSE)
    data_feed.compute_indicators(config.STOCK_UNIVERSE)
    print(f"  {green('Data and indicators ready.')}\n")

    # ── Step 12: Calculate gaps ──
    data_feed.calculate_gaps(config.STOCK_UNIVERSE)

    # Write initial state so Slack AI knows the bot is alive before the first tick
    _write_state()

    # ── Step 13: Set up scheduler ──
    scheduler = BackgroundScheduler(timezone=ET)

    # Pre-market: refresh data at 9:15 AM
    scheduler.add_job(
        pre_market_prep, "cron",
        day_of_week="mon-fri", hour=9, minute=15,
        id="pre_market",
    )

    # Main trading loop: every 5 minutes during market hours
    scheduler.add_job(
        trading_tick, "cron",
        day_of_week="mon-fri", hour="9-15", minute="*/5",
        id="trading_tick",
    )

    # ORB computation at 10:00 AM
    scheduler.add_job(
        compute_orb, "cron",
        day_of_week="mon-fri", hour=10, minute=0,
        id="compute_orb",
    )

    # Time stop: close intraday at 3:30 PM
    scheduler.add_job(
        time_stop_close, "cron",
        day_of_week="mon-fri", hour=15, minute=30,
        id="time_stop",
    )

    # End of day: 4:00 PM summary
    scheduler.add_job(
        end_of_day_summary, "cron",
        day_of_week="mon-fri", hour=16, minute=1,
        id="eod_summary",
    )

    # Daily reset at midnight
    scheduler.add_job(
        daily_reset, "cron",
        day_of_week="mon-fri", hour=0, minute=0,
        id="daily_reset",
    )

    scheduler.start()
    print(f"  {green('Scheduler started.')} Waiting for market events...\n")

    # ── Step 14: If market is currently open, run an immediate tick ──
    now = now_et()
    if (now.weekday() < 5 and
            config.MARKET_OPEN <= now.time() <= config.MARKET_CLOSE):
        print(f"  {cyan('Market is open — running initial scan...')}")
        if now.time() >= config.ORB_END:
            compute_orb()
        trading_tick()

    # ── Step 15: Keep alive ──
    try:
        while not _shutting_down:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        graceful_shutdown()


# ─── Scheduled Functions ─────────────────────────────────────────────────────

def pre_market_prep():
    """9:15 AM — download fresh data, calculate gaps, print briefing."""
    global _orb_computed
    _orb_computed = False

    log.info("=== PRE-MARKET PREP (9:15 AM) ===")
    print(f"\n  {cyan(bold('PRE-MARKET PREP — 9:15 AM'))}")

    # Refresh daily data
    data_feed.download_historical(config.STOCK_UNIVERSE)
    data_feed.compute_indicators(config.STOCK_UNIVERSE)

    # Reset daily risk
    portfolio_value = acct_mgr.get_portfolio_value()
    risk_mgr.init_daily(portfolio_value)

    # Calculate gaps
    data_feed.calculate_gaps(config.STOCK_UNIVERSE)

    # Print daily briefing
    pdt_count = acct_mgr.get_day_trade_count()
    mode = "SWING ONLY (PDT)" if pdt_count >= config.PDT_MAX_DAY_TRADES else "FULL"

    print(f"  Portfolio:     {fmt_price(portfolio_value)}")
    print(f"  PDT Status:    {pdt_count}/{config.PDT_MAX_DAY_TRADES}")
    print(f"  Strategy Mode: {mode}")
    print(f"  Gaps: {data_feed._notable_gaps()}")
    separator()


def compute_orb():
    """10:00 AM — compute opening ranges for ORB strategy."""
    global _orb_computed
    if _orb_computed:
        return

    log.info("=== COMPUTING OPENING RANGES (10:00 AM) ===")

    # Poll the latest bar per symbol, then backfill the full 9:25-10:05
    # window for any symbol that missed bars (IEX delay or late tick).
    data_feed.poll_latest_bars(config.STOCK_UNIVERSE)
    data_feed.download_opening_range_bars(config.STOCK_UNIVERSE)
    data_feed.compute_opening_ranges(config.STOCK_UNIVERSE)
    _orb_computed = True

    n = len(data_feed.opening_ranges)
    print(f"  {cyan(f'Opening ranges computed for {n} symbols')}")


def trading_tick():
    """
    Main trading loop — runs every 5 minutes during market hours.
    Checks exits on open positions, then scans for new entries.
    """
    now = now_et()

    # Skip if outside market hours
    if now.time() < config.MARKET_OPEN or now.time() > config.MARKET_CLOSE:
        return

    # Skip if halted
    if risk_mgr.is_halted() or risk_mgr.is_daily_halted():
        return

    log.debug(f"=== TRADING TICK {now.strftime('%H:%M:%S')} ===")

    # ── Poll latest bars ──
    try:
        new_bars = data_feed.poll_latest_bars(config.STOCK_UNIVERSE)
        if new_bars:
            log.debug(f"  Got {len(new_bars)} new bars")
    except Exception as e:
        log.error(f"Bar poll error: {e}")
        return

    # ── Check exits on open positions ──
    _check_exits()

    # ── Check for new entries (skip in last 30 min) ──
    if now.time() < config.TIME_STOP:
        _scan_entries()

    _write_state()


def _check_exits():
    """Check exit conditions for all tracked positions."""
    for symbol in list(risk_mgr.positions.keys()):
        pos = risk_mgr.positions[symbol]

        should_exit = False
        reason = ""

        if pos.strategy == "EMA_VWAP":
            row = data_feed.get_latest_5m(symbol)
            should_exit, reason = s1.check_exit(pos, row)
            # Update high water for trailing
            if row is not None:
                risk_mgr.update_high_water(symbol, row.get("Close", 0))

        elif pos.strategy == "ORB":
            row = data_feed.get_latest_5m(symbol)
            orb = data_feed.opening_ranges.get(symbol, {})
            should_exit, reason = s2.check_exit(pos, row, orb)

        elif pos.strategy == "RSI_BOUNCE":
            row = data_feed.get_latest_daily(symbol)
            # Calculate bars held in trading days
            entry_dt = datetime.strptime(pos.entry_time[:10], "%Y-%m-%d")
            bars_held = (now_et().date() - entry_dt.date()).days
            should_exit, reason = s3.check_exit(pos, row, bars_held)

        if should_exit:
            _execute_exit(symbol, reason)


def _scan_entries():
    """Scan for new entry signals across the universe."""
    can_dt = acct_mgr.can_day_trade()
    now = now_et()

    # Check if we can even take new positions
    ok, msg = risk_mgr.can_trade()
    if not ok:
        return

    # Prioritize Tier 1 stocks first
    scan_order = config.TIER_1 + config.TIER_2

    for symbol in scan_order:
        # Re-check capacity each iteration (may have filled a position)
        ok, msg = risk_mgr.can_trade()
        if not ok:
            break

        # Skip if already holding
        if symbol in risk_mgr.positions:
            continue

        # Get strategy selection
        daily_row = data_feed.get_latest_daily(symbol)
        gap_pct = data_feed.gaps.get(symbol, 0.0)
        strategies = strategy_selector.get_applicable_strategies(
            symbol, daily_row, gap_pct, can_dt
        )

        for strat_name, strat_reason in strategies:
            signal = "NONE"

            if strat_name == "EMA_VWAP":
                if not can_dt:
                    continue  # intraday strategy, need PDT clearance
                row = data_feed.get_latest_5m(symbol)
                signal = s1.check_signal(row)

            elif strat_name == "ORB":
                if not can_dt:
                    continue
                if now.time() < config.ORB_END:
                    continue  # ORB only after 10 AM
                row = data_feed.get_latest_5m(symbol)
                orb = data_feed.opening_ranges.get(symbol)
                if orb:
                    daily = data_feed.get_latest_daily(symbol)
                    signal = s2.check_signal(row, orb, daily)

            elif strat_name == "RSI_BOUNCE":
                signal = s3.check_signal(daily_row)

            if signal == "BUY":
                _execute_entry(symbol, strat_name)
                break  # one entry per symbol per tick


def _execute_entry(symbol: str, strategy: str):
    """Execute a buy entry for a symbol."""
    price = data_feed.get_last_price(symbol)
    if price <= 0:
        return

    # Calculate position size
    qty, dollar_amount = risk_mgr.calc_position_size(price)
    if qty <= 0:
        return

    # Calculate stops
    if strategy == "EMA_VWAP":
        row = data_feed.get_latest_5m(symbol)
        atr_val = row.get("atr", 0) if row is not None else 0
        if atr_val <= 0:
            return
        sl, tp, trail = s1.calc_stops(price, atr_val)
        details = s1.entry_details(row)
    elif strategy == "ORB":
        orb = data_feed.opening_ranges.get(symbol, {})
        row = data_feed.get_latest_5m(symbol)
        sl, tp = s2.calc_stops(price, orb)
        trail = None
        details = s2.entry_details(row, orb)
    elif strategy == "RSI_BOUNCE":
        daily_row = data_feed.get_latest_daily(symbol)
        sl = s3.calc_stops(price)
        tp = None  # exits via RSI/BB, not fixed target
        trail = None
        details = s3.entry_details(daily_row)
    else:
        return

    # Calculate risk
    risk_dollars, risk_pct = risk_mgr.risk_per_trade(price, sl, qty)
    confidence = explainer.calc_confidence(strategy, details)
    pdt_count = acct_mgr.get_day_trade_count()
    buying_power = acct_mgr.get_buying_power()

    # Print entry explanation
    explainer.explain_entry(
        symbol=symbol, strategy=strategy, side="long",
        price=price, qty=qty, stop_loss=sl,
        take_profit=tp, details=details,
        risk_dollars=risk_dollars, risk_pct=risk_pct,
        pdt_count=pdt_count, buying_power=buying_power,
        confidence=confidence,
    )

    # Submit order
    result = order_mgr.submit_buy(
        symbol=symbol, qty=qty, price=price,
        strategy=strategy, stop_loss=sl, take_profit=tp,
        trail_activate=trail,
    )

    if result and result["filled"]:
        fill_price = result["fill_price"]
        filled_qty = result.get("filled_qty", qty)

        # Recalculate stops with actual fill price
        if strategy == "EMA_VWAP":
            sl, tp, trail = s1.calc_stops(fill_price, atr_val)

        pos = LivePosition(
            symbol=symbol,
            side="long",
            entry_price=fill_price,
            qty=filled_qty,
            entry_time=now_et().strftime("%Y-%m-%d %H:%M:%S"),
            strategy=strategy,
            stop_loss=sl,
            take_profit=tp if tp else 0,
            trail_activate=trail,
            trail_stop_atr=config.S1_TRAIL_STOP_ATR if trail else None,
            high_water=fill_price,
            entry_value=fill_price * filled_qty,
        )
        risk_mgr.record_entry(pos)
        _write_state()


def _execute_exit(symbol: str, reason: str):
    """Execute a sell exit for a symbol."""
    price = data_feed.get_last_price(symbol)
    pos = risk_mgr.positions.get(symbol)
    if not pos or price <= 0:
        return

    result = order_mgr.submit_sell(
        symbol=symbol, qty=pos.qty, price=price, reason=reason
    )

    if result and result["filled"]:
        exit_price = result["fill_price"]
        trade = risk_mgr.record_exit(symbol, exit_price, reason)

        if trade:
            # Calculate hold time
            entry_dt = datetime.strptime(pos.entry_time, "%Y-%m-%d %H:%M:%S")
            hold_delta = now_et().replace(tzinfo=None) - entry_dt
            if hold_delta.days > 0:
                hold_str = f"{hold_delta.days}d"
            else:
                hold_str = f"{hold_delta.seconds // 60}m"

            explainer.explain_exit(
                symbol=symbol, strategy=pos.strategy,
                entry_price=pos.entry_price, exit_price=exit_price,
                qty=pos.qty, pnl=trade.pnl, pnl_pct=trade.pnl_pct,
                reason=reason, hold_time=hold_str,
            )
            _write_state()


def time_stop_close():
    """3:30 PM — close all intraday positions (EMA_VWAP and ORB)."""
    log.info("=== TIME STOP (3:30 PM) ===")
    print(f"\n  {yellow(bold('TIME STOP — Closing intraday positions'))}")

    for symbol in list(risk_mgr.positions.keys()):
        pos = risk_mgr.positions[symbol]
        if pos.strategy in ("EMA_VWAP", "ORB"):
            _execute_exit(symbol, "time_stop")

    print(f"  {green('Intraday positions closed.')}")


def end_of_day_summary():
    """4:00 PM — print daily summary, save logs."""
    log.info("=== END OF DAY SUMMARY ===")

    portfolio_value = acct_mgr.get_portfolio_value()
    daily_pnl = risk_mgr.get_daily_pnl()
    start_val = risk_mgr._daily_start_value or portfolio_value
    daily_return = (daily_pnl / start_val * 100) if start_val > 0 else 0
    cumulative_return = ((portfolio_value - config.STARTING_CAPITAL) /
                         config.STARTING_CAPITAL * 100)

    trades = risk_mgr.trades_today
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    banner("END OF DAY SUMMARY")
    print(f"  Portfolio Value: {fmt_price(portfolio_value)}")
    print(f"  Daily P&L:       {fmt_pnl(daily_pnl)} ({fmt_pct(daily_return)})")
    print(f"  Cumulative:      {fmt_pct(cumulative_return)}")
    print(f"  Trades Today:    {len(trades)} "
          f"({len(wins)} wins, {len(losses)} losses)")
    print(f"  PDT Status:      "
          f"{acct_mgr.get_day_trade_count()}/{config.PDT_MAX_DAY_TRADES}")

    if trades:
        win_rate = len(wins) / len(trades) * 100
        print(f"  Win Rate:        {fmt_pct(win_rate)}")
        separator()
        print(f"  {'Symbol':<8} {'Strategy':<12} {'P&L':>10} {'Reason':<15}")
        print(f"  {'-'*50}")
        for t in trades:
            pnl_s = fmt_pnl(t.pnl)
            print(f"  {t.symbol:<8} {t.strategy:<12} {pnl_s:>10} {t.exit_reason:<15}")

        # Strategy breakdown
        strats = {}
        for t in trades:
            if t.strategy not in strats:
                strats[t.strategy] = {"trades": 0, "wins": 0, "pnl": 0}
            strats[t.strategy]["trades"] += 1
            strats[t.strategy]["pnl"] += t.pnl
            if t.pnl > 0:
                strats[t.strategy]["wins"] += 1

        separator()
        print(f"  {'Strategy':<12} {'Trades':>7} {'Win%':>7} {'P&L':>10}")
        for name, stats in strats.items():
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            print(f"  {name:<12} {stats['trades']:>7} {wr:>6.1f}% {fmt_pnl(stats['pnl']):>10}")

    separator()
    print()

    # Save daily log
    risk_mgr.save_daily_log()


def daily_reset():
    """Midnight — reset daily state for next trading day."""
    global _orb_computed
    _orb_computed = False
    log.info("=== DAILY RESET ===")


# ─── State Export ────────────────────────────────────────────────────────────

def _write_state():
    """Write live bot state to data/bot_state.json so the Slack AI can read it."""
    try:
        positions = []
        for sym, pos in risk_mgr.positions.items():
            price = data_feed.get_last_price(sym)
            unrealized = round((price - pos.entry_price) * pos.qty, 2) if price > 0 else 0
            positions.append({
                "symbol": sym,
                "strategy": pos.strategy,
                "entry_price": pos.entry_price,
                "qty": pos.qty,
                "entry_time": pos.entry_time,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit if pos.take_profit else None,
                "current_price": price,
                "unrealized_pnl": unrealized,
            })

        trades = []
        for t in risk_mgr.trades_today:
            trades.append({
                "symbol": t.symbol,
                "strategy": t.strategy,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "qty": t.qty,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 4),
                "exit_reason": t.exit_reason,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
            })

        state = {
            "timestamp": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
            "running": True,
            "portfolio_value": acct_mgr.get_portfolio_value(),
            "buying_power": acct_mgr.get_buying_power(),
            "daily_pnl": round(risk_mgr.get_daily_pnl(), 2),
            "pdt_count": acct_mgr.get_day_trade_count(),
            "pdt_limit": config.PDT_MAX_DAY_TRADES,
            "halted": risk_mgr.is_halted() or risk_mgr.is_daily_halted(),
            "open_positions": positions,
            "trades_today": trades,
            "stock_universe": config.STOCK_UNIVERSE,
            "strategies": {
                "EMA_VWAP": "Intraday 5-min momentum using EMA(9/21/55) crossover above VWAP with ATR stops",
                "ORB": "Intraday opening range breakout — buys breakout above first-30min high after 10am",
                "RSI_BOUNCE": "Swing trade mean reversion — buys when daily RSI(7) < 25 near lower Bollinger Band",
            },
            "risk_limits": {
                "max_position_pct": config.MAX_POSITION_PCT,
                "max_concurrent": config.MAX_CONCURRENT_POSITIONS,
                "max_daily_loss_pct": config.MAX_DAILY_LOSS_PCT,
                "max_order_value": config.MAX_ORDER_VALUE,
            },
        }

        state_path = Path(__file__).parent / config.DATA_DIR / "bot_state.json"
        state_path.parent.mkdir(exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


# ─── Shutdown ────────────────────────────────────────────────────────────────

def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    graceful_shutdown()


def graceful_shutdown():
    """Cancel orders, optionally close positions, save logs, exit."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True

    print(f"\n  {yellow(bold('Shutting down gracefully...'))}")
    log.info("=== GRACEFUL SHUTDOWN ===")

    # Stop scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

    # Cancel all pending orders
    try:
        api.cancel_all_orders()
        log.info("All pending orders cancelled")
    except Exception as e:
        log.error(f"Failed to cancel orders: {e}")

    # Close positions if configured
    if env_config and env_config.get("close_on_shutdown"):
        print(f"  {yellow('Closing all positions (CLOSE_ON_SHUTDOWN=true)...')}")
        order_mgr.close_all_positions()
    else:
        positions = acct_mgr.get_open_positions()
        if positions:
            print(f"  {yellow(f'{len(positions)} positions left open (CLOSE_ON_SHUTDOWN=false)')}")

    # End of day summary
    end_of_day_summary()

    # Final state
    portfolio_value = acct_mgr.get_portfolio_value()
    print(f"\n  {bold('Final Portfolio Value:')} {fmt_price(portfolio_value)}")
    print(f"  {green('Bot shut down safely.')}\n")

    sys.exit(0)


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
