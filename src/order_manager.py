"""
Order Manager — submit limit orders, poll for fills, cancel unfilled,
manage stop-loss orders, track all order events.
"""
import time
from logger_setup import get_logger
import config
from utils import now_et, fmt_price, fmt_shares, green, red, yellow, bold


class OrderManager:
    """Handles all order lifecycle: submit, poll, cancel, stop orders."""

    def __init__(self, api, risk_manager, account_manager):
        self.api = api
        self.risk = risk_manager
        self.acct = account_manager
        self.log = get_logger()

        # Track pending stop orders: {symbol: order_id}
        self.stop_orders = {}

    # ─── Submit Buy Order ────────────────────────────────────────────────

    def submit_buy(self, symbol: str, qty: float, price: float,
                   strategy: str, stop_loss: float,
                   take_profit: float = None,
                   trail_activate: float = None, client_order_id: str = None) -> dict:
        """
        Submit a limit buy order with fractional shares.
        Returns {"filled": bool, "fill_price": float, "order_id": str}
        or None on failure.
        """
        # Calculate limit price (0.05% above current for fast fill)
        limit_price = round(price * (1 + config.LIMIT_OFFSET_PCT), 2)
        order_value = limit_price * qty

        # ── Pre-submission validation ──
        ok, reason = self.risk.validate_order(symbol, limit_price, qty,strategy=strategy)
        if not ok:
            self.log.warning(f"Order rejected: {symbol} — {reason}")
            return None

        self.log.info(
            f"SUBMITTING BUY: {symbol} | {fmt_shares(qty)} shares "
            f"@ {fmt_price(limit_price)} limit | "
            f"Value: {fmt_price(order_value)} | Strategy: {strategy}"
        )

        try:
            order = self._submit_limit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                limit_price=limit_price, client_order_id=client_order_id,
            )
        except Exception as e:
            self.log.error(f"Order submission failed for {symbol}: {e}")
            # A timeout can mean the broker accepted the order. Never blindly
            # submit a second entry; require reconciliation before another tick.
            self.risk._bot_halted = True
            return None

        if order is None:
            return None

        order_id = order.id
        self.log.info(f"  Order submitted: {order_id}")

        # ── Poll for fill ──
        result = self._poll_fill(order_id, symbol)

        if result["filled"]:
            fill_price = result["fill_price"]
            filled_qty = result["filled_qty"]
            print(f"  {green('BUY FILLED')} {symbol} | "
                  f"{fmt_shares(filled_qty)} shares @ {fmt_price(fill_price)} | "
                  f"Strategy: {strategy}")

            # Submit stop-loss order
            self._submit_stop_order(symbol, filled_qty, stop_loss)

            return {
                "filled": True,
                "fill_price": fill_price,
                "filled_qty": filled_qty,
                "order_id": order_id,
            }
        else:
            self.log.warning(f"  Order NOT filled within timeout — cancelling")
            self._cancel_order(order_id, symbol)
            return {"filled": False, "fill_price": 0, "order_id": order_id}

    # ─── Submit Sell Order ───────────────────────────────────────────────

    def submit_sell(self, symbol: str, qty: float, price: float,
                    reason: str) -> dict:
        """
        Submit a limit sell order (to close a position).
        Returns {"filled": bool, "fill_price": float}
        """
        # Cancel any existing stop order for this symbol
        if not self._cancel_stop_order(symbol):
            return {"filled": False, "fill_price": 0, "filled_qty": 0}

        # Limit price slightly below market for fast fill
        limit_price = round(price * (1 - config.LIMIT_OFFSET_PCT), 2)

        self.log.info(
            f"SUBMITTING SELL: {symbol} | {fmt_shares(qty)} shares "
            f"@ {fmt_price(limit_price)} limit | Reason: {reason}"
        )

        try:
            order = self._submit_limit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                limit_price=limit_price,
            )
        except Exception as e:
            self.log.error(f"Sell order failed for {symbol}: {e}")
            self.risk._bot_halted = True
            # Submission outcome is ambiguous. A second order could oversell.
            raise RuntimeError("Exit submission unresolved; reconcile broker orders") from e

        if order is None:
            return {"filled": False, "fill_price": 0}

        result = self._poll_fill(order.id, symbol)
        self._restore_stop(symbol, max(0, qty - result["filled_qty"]))

        if result["filled"]:
            fill_price = result["fill_price"]
            print(f"  {red('SELL FILLED')} {symbol} | "
                  f"{fmt_shares(qty)} shares @ {fmt_price(fill_price)} | "
                  f"Reason: {reason}")

            # Check if this was a day trade
            self._check_day_trade(symbol)

            return {
                "filled": True,
                "fill_price": fill_price,
                "filled_qty": result["filled_qty"],
            }
        else:
            self.log.warning(f"  Sell order not filled — cancelling")
            self._cancel_order(order.id, symbol)
            return {"filled": False, "fill_price": 0}

    # ─── Submit Short Order (open short) ─────────────────────────────────

    def submit_short(self, symbol: str, qty: float, price: float,
                     strategy: str, stop_loss: float,
                     take_profit: float = None,
                     trail_activate: float = None, client_order_id: str = None) -> dict:
        """
        Open a SHORT position: sell-to-open via a limit sell slightly below
        market (for fast fill), then set a BUY-stop above entry as the stop loss.
        Caller is responsible for ensuring shorts are permitted (TRADING_MODE,
        Alpaca account.shorting_enabled).
        """
        limit_price = round(price * (1 - config.LIMIT_OFFSET_PCT), 2)
        order_value = limit_price * qty

        ok, reason = self.risk.validate_order(symbol, limit_price, qty,strategy=strategy)
        if not ok:
            self.log.warning(f"Short rejected: {symbol} — {reason}")
            return None

        self.log.info(
            f"SUBMITTING SHORT: {symbol} | {fmt_shares(qty)} shares "
            f"@ {fmt_price(limit_price)} limit sell | "
            f"Value: {fmt_price(order_value)} | Strategy: {strategy}"
        )

        try:
            order = self._submit_limit_order(
                symbol=symbol, qty=qty, side="sell", limit_price=limit_price, client_order_id=client_order_id,
            )
        except Exception as e:
            self.log.error(f"Short submission failed for {symbol}: {e}")
            self.risk._bot_halted = True
            return None

        if order is None:
            return None

        result = self._poll_fill(order.id, symbol)
        if result["filled"]:
            fill_price = result["fill_price"]
            filled_qty = result["filled_qty"]
            print(f"  {yellow('SHORT FILLED')} {symbol} | "
                  f"{fmt_shares(filled_qty)} shares @ {fmt_price(fill_price)} | "
                  f"Strategy: {strategy}")

            # Stop for a short = BUY stop above entry
            self._submit_stop_order(symbol, filled_qty, stop_loss, side="buy")
            return {
                "filled": True, "fill_price": fill_price,
                "filled_qty": filled_qty, "order_id": order.id,
            }
        self.log.warning(f"  Short order NOT filled within timeout — cancelling")
        self._cancel_order(order.id, symbol)
        return {"filled": False, "fill_price": 0, "order_id": order.id}

    # ─── Submit Cover Order (close short) ────────────────────────────────

    def submit_cover(self, symbol: str, qty: float, price: float,
                     reason: str) -> dict:
        """Close a SHORT: buy-to-cover via a limit buy slightly above market."""
        if not self._cancel_stop_order(symbol):
            return {"filled": False, "fill_price": 0, "filled_qty": 0}

        limit_price = round(price * (1 + config.LIMIT_OFFSET_PCT), 2)
        self.log.info(
            f"SUBMITTING COVER: {symbol} | {fmt_shares(qty)} shares "
            f"@ {fmt_price(limit_price)} limit buy | Reason: {reason}"
        )

        try:
            order = self._submit_limit_order(
                symbol=symbol, qty=qty, side="buy", limit_price=limit_price,
            )
        except Exception as e:
            self.log.error(f"Cover order failed for {symbol}: {e}")
            self.risk._bot_halted = True
            raise RuntimeError("Cover submission unresolved; reconcile broker orders") from e

        if order is None:
            return {"filled": False, "fill_price": 0}

        result = self._poll_fill(order.id, symbol)
        self._restore_stop(symbol, max(0, qty - result["filled_qty"]))
        if result["filled"]:
            fill_price = result["fill_price"]
            print(f"  {green('COVER FILLED')} {symbol} | "
                  f"{fmt_shares(qty)} shares @ {fmt_price(fill_price)} | "
                  f"Reason: {reason}")
            self._check_day_trade(symbol)
            return {"filled": True, "fill_price": fill_price,
                    "filled_qty": result["filled_qty"]}

        self.log.warning(f"  Cover not filled — cancelling")
        self._cancel_order(order.id, symbol)
        return {"filled": False, "fill_price": 0}

    # ─── Close All Positions ─────────────────────────────────────────────

    def close_all_positions(self):
        """Emergency close all positions (for kill switch / shutdown)."""
        self.log.warning("CLOSING ALL POSITIONS")

        # Cancel all open orders first
        try:
            self.api.cancel_all_orders()
            self.log.info("  All open orders cancelled")
        except Exception as e:
            self.log.error(f"  Failed to cancel orders: {e}")

        # Close each position
        positions = self.acct.get_open_positions()
        for pos in positions:
            sym = pos.symbol
            qty = float(pos.qty)
            try:
                self.api.close_position(sym)
                self.log.info(f"  Closed position: {sym} ({qty} shares)")
            except Exception as e:
                self.log.error(f"  Failed to close {sym}: {e}")

        self.stop_orders.clear()

    # ─── Internal Order Helpers ──────────────────────────────────────────

    def _submit_limit_order(self, symbol, qty, side, limit_price,
                            extended_hours: bool = False, client_order_id: str = None):
        """Submit a limit order through Alpaca API.
        extended_hours=True routes to pre/post market (limit-only, day TIF).
        Alpaca rejects fractional qty for ext-hours, so callers must pass whole shares.
        """
        kwargs = dict(
            symbol=symbol,
            qty=qty,
            side=side,
            type="limit",
            time_in_force="day",
            limit_price=str(limit_price),
        )
        if client_order_id:
            kwargs["client_order_id"] = client_order_id
        if extended_hours:
            kwargs["extended_hours"] = True
        return self.api.submit_order(**kwargs)

    def submit_buy_premarket(self, symbol: str, qty: float, ref_price: float,
                             strategy: str, stop_loss: float) -> dict:
        """
        Submit a pre-market LIMIT BUY (extended_hours=True). No fill poll —
        order rests until pre-market liquidity arrives. Stop-loss is queued
        immediately as GTC; it won't fire until 9:30 RTH (Alpaca rule).
        Returns {"submitted": bool, "order_id": str|None, "limit_price": float}.
        """
        qty = int(qty)  # ext-hours rejects fractional shares
        if qty < 1:
            self.log.warning(f"Premarket BUY {symbol}: qty<1 after rounding, skipping")
            return {"submitted": False, "order_id": None, "limit_price": 0}

        limit_price = round(ref_price * (1 + config.PREMARKET_LIMIT_OFFSET_PCT), 2)

        ok, reason = self.risk.validate_order(symbol, limit_price, qty,strategy=strategy)
        if not ok:
            self.log.warning(f"Premarket order rejected: {symbol} — {reason}")
            return {"submitted": False, "order_id": None, "limit_price": limit_price}

        self.log.info(
            f"PREMARKET BUY: {symbol} | {qty} shares @ {fmt_price(limit_price)} "
            f"(ref {fmt_price(ref_price)}) | Strategy: {strategy}"
        )
        try:
            order = self._submit_limit_order(
                symbol=symbol, qty=qty, side="buy",
                limit_price=limit_price, extended_hours=True,
            )
        except Exception as e:
            self.log.error(f"Premarket order failed for {symbol}: {e}")
            return {"submitted": False, "order_id": None, "limit_price": limit_price}

        if order is None:
            return {"submitted": False, "order_id": None, "limit_price": limit_price}

        self._submit_stop_order(symbol, qty, stop_loss)  # queued; fires at 9:30
        return {"submitted": True, "order_id": order.id, "limit_price": limit_price}

    def _submit_stop_order(self, symbol, qty, stop_price, side: str = "sell"):
        """
        Submit a stop-loss order for an open position.
        side="sell" for a long stop (below entry), side="buy" for a short stop (above entry).
        """
        stop_price = round(stop_price, 2)
        # Alpaca rejects GTC stops on fractional qty — fractional must be DAY.
        is_fractional = float(qty) != int(float(qty))
        tif = "day" if is_fractional else "gtc"
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type="stop",
                time_in_force=tif,
                stop_price=str(stop_price),
            )
            self.stop_orders[symbol] = order.id
            self.log.info(f"  Stop-loss set ({side}) for {symbol} @ {fmt_price(stop_price)}")
        except Exception as e:
            self.log.error(f"  Failed to set stop for {symbol}: {e}")
            self.risk._bot_halted = True

    def _restore_stop(self, symbol, remaining_qty):
        pos = self.risk.positions.get(symbol)
        if pos and remaining_qty > 1e-8:
            self._submit_stop_order(symbol, remaining_qty, pos.stop_loss,
                                    side="buy" if pos.side == "short" else "sell")

    def _cancel_stop_order(self, symbol):
        """Wait for cancellation; never exit against an unresolved/filled stop."""
        order_id = self.stop_orders.get(symbol)
        if not order_id:
            return True
        try:
            self.api.cancel_order(order_id)
            for _ in range(5):
                order = self.api.get_order(order_id)
                if order.status == "filled" or float(order.filled_qty or 0) > 0:
                    self.risk._bot_halted = True
                    return False
                if order.status in ("canceled", "cancelled", "expired", "rejected"):
                    self.stop_orders.pop(symbol, None)
                    return True
                time.sleep(config.ORDER_POLL_INTERVAL)
        except Exception:
            pass
        self.risk._bot_halted = True
        self.log.error(f"Stop cancellation unresolved for {symbol}; reconcile broker orders")
        return False

    def _poll_fill(self, order_id, symbol) -> dict:
        """Account for partial fills and cancellation/fill races before returning."""
        terminal = {"filled", "canceled", "cancelled", "expired", "rejected"}
        def result(order):
            qty = float(order.filled_qty or 0)
            import math
            price=float(order.filled_avg_price or 0)
            if not math.isfinite(qty) or qty<0 or (qty>0 and (not math.isfinite(price) or price<=0)):
                self.risk._bot_halted=True
                raise RuntimeError('Broker fill price/quantity invalid; reconcile before another order')
            try:
                from research.notifications import execution_event
                execution_event(str(order_id),symbol,str(order.status),qty,price,str(getattr(order,'side','unknown')))
            except Exception:
                self.log.warning('Execution audit/notification persistence unavailable')
            return {"filled": qty > 0, "fill_price": price, "filled_qty": qty}
        elapsed = 0
        while elapsed < config.ORDER_POLL_TIMEOUT:
            try:
                order = self.api.get_order(order_id)
                if order.status in terminal:
                    return result(order)
            except Exception as e:
                self.log.debug(f"Order status unavailable for {symbol}: {type(e).__name__}")
            time.sleep(config.ORDER_POLL_INTERVAL)
            elapsed += config.ORDER_POLL_INTERVAL
        self._cancel_order(order_id, symbol)
        # Cancellation is asynchronous. Re-read until the order is terminal;
        # a partial fill must not be mistaken for an entirely unfilled order.
        for _ in range(5):
            try:
                order = self.api.get_order(order_id)
                if order.status in terminal:
                    return result(order)
            except Exception:
                pass
            time.sleep(config.ORDER_POLL_INTERVAL)
        self.risk._bot_halted = True
        raise RuntimeError(f"Order {order_id} unresolved; entries halted pending broker reconciliation")

    def _cancel_order(self, order_id, symbol):
        """Cancel an unfilled order."""
        try:
            self.api.cancel_order(order_id)
            self.log.info(f"  Cancelled unfilled order for {symbol}")
        except Exception as e:
            self.log.debug(f"  Cancel failed for {symbol}: {e}")

    def _check_day_trade(self, symbol):
        """
        Check if selling this symbol constitutes a day trade
        (bought and sold same day).
        """
        # Check our risk manager's tracked positions
        pos = self.risk.positions.get(symbol)
        if pos:
            entry_date = pos.entry_time[:10]
            today = now_et().strftime("%Y-%m-%d")
            if entry_date == today:
                self.acct.record_day_trade(symbol)
