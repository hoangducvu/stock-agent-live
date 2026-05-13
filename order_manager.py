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
                   trail_activate: float = None) -> dict:
        """
        Submit a limit buy order with fractional shares.
        Returns {"filled": bool, "fill_price": float, "order_id": str}
        or None on failure.
        """
        # Calculate limit price (0.05% above current for fast fill)
        limit_price = round(price * (1 + config.LIMIT_OFFSET_PCT), 2)
        order_value = limit_price * qty

        # ── Pre-submission validation ──
        ok, reason = self.risk.validate_order(symbol, limit_price, qty)
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
                limit_price=limit_price,
            )
        except Exception as e:
            self.log.error(f"Order submission failed for {symbol}: {e}")
            # Retry once after delay
            time.sleep(config.API_RETRY_DELAY)
            try:
                order = self._submit_limit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    limit_price=limit_price,
                )
            except Exception as e2:
                self.log.error(f"Order retry also failed for {symbol}: {e2}")
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
        self._cancel_stop_order(symbol)

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
            # Try market order as last resort for exits
            try:
                self.log.warning(f"  Trying market order for {symbol} exit")
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="market",
                    time_in_force="day",
                )
            except Exception as e2:
                self.log.error(f"  Market sell also failed: {e2}")
                return {"filled": False, "fill_price": 0}

        if order is None:
            return {"filled": False, "fill_price": 0}

        result = self._poll_fill(order.id, symbol)

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

    def _submit_limit_order(self, symbol, qty, side, limit_price):
        """Submit a limit order through Alpaca API."""
        return self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type="limit",
            time_in_force="day",
            limit_price=str(limit_price),
        )

    def _submit_stop_order(self, symbol, qty, stop_price):
        """Submit a stop-loss sell order for an open position."""
        stop_price = round(stop_price, 2)
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="stop",
                time_in_force="gtc",
                stop_price=str(stop_price),
            )
            self.stop_orders[symbol] = order.id
            self.log.info(f"  Stop-loss set for {symbol} @ {fmt_price(stop_price)}")
        except Exception as e:
            self.log.error(f"  Failed to set stop for {symbol}: {e}")

    def _cancel_stop_order(self, symbol):
        """Cancel an existing stop order for a symbol."""
        order_id = self.stop_orders.pop(symbol, None)
        if order_id:
            try:
                self.api.cancel_order(order_id)
                self.log.debug(f"  Cancelled stop order for {symbol}")
            except Exception:
                pass  # Order may already be filled/cancelled

    def _poll_fill(self, order_id, symbol) -> dict:
        """Poll for order fill status. Returns fill info."""
        elapsed = 0
        while elapsed < config.ORDER_POLL_TIMEOUT:
            try:
                order = self.api.get_order(order_id)
                status = order.status

                if status == "filled":
                    return {
                        "filled": True,
                        "fill_price": float(order.filled_avg_price),
                        "filled_qty": float(order.filled_qty),
                    }
                elif status == "partially_filled":
                    self.log.info(
                        f"  {symbol}: partial fill "
                        f"({order.filled_qty}/{order.qty})"
                    )
                elif status in ("cancelled", "expired", "rejected"):
                    self.log.warning(f"  {symbol}: order {status}")
                    return {"filled": False, "fill_price": 0, "filled_qty": 0}

            except Exception as e:
                self.log.debug(f"  Poll error for {symbol}: {e}")

            time.sleep(config.ORDER_POLL_INTERVAL)
            elapsed += config.ORDER_POLL_INTERVAL

        return {"filled": False, "fill_price": 0, "filled_qty": 0}

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
