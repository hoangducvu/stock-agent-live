"""Read-only adoption of broker state; never invent ownership or replace orders."""
import math
from risk_manager import LivePosition

def reconcile_broker_state(api,risk,log):
    positions=api.list_positions()
    orders=api.list_orders(status='open',limit=500)
    parsed={}
    for position in positions:
        symbol=position.symbol;qty=float(position.qty);entry=float(position.avg_entry_price)
        if not symbol or not math.isfinite(qty) or not math.isfinite(entry) or qty==0 or entry<=0:
            raise RuntimeError('Invalid broker position; reconciliation required')
        side='short' if str(getattr(position,'side','')).lower()=='short' or qty<0 else 'long'
        parsed[symbol]=(abs(qty),entry,side)
    pending=set()
    for order in orders:
        symbol=getattr(order,'symbol',None)
        if not symbol:raise RuntimeError('Broker order missing symbol')
        pending.add(symbol)
    risk.pending_symbols=pending
    for symbol,(qty,entry,side) in parsed.items():
        current=risk.positions.get(symbol)
        if current is None or current.strategy=='EXTERNAL' or current.side!=side:
            if current is not None and current.strategy!='EXTERNAL' and current.side!=side:
                risk._bot_halted=True
                log.warning('Broker side changed for %s; engine ownership suspended',symbol)
            # No original thesis/entry time/stop ownership is known. Observe the
            # holding without selling it or cancelling any broker protection.
            risk.positions[symbol]=LivePosition(symbol=symbol,side=side,entry_price=entry,qty=qty,
                entry_time='',strategy='EXTERNAL',stop_loss=0,take_profit=0,entry_value=entry*qty)
            if current is None:log.info('Existing broker holding monitored separately: %s %s qty=%s',symbol,side,qty)
        elif abs(current.qty-qty)>1e-8:
            current.qty=qty;risk._bot_halted=True
            log.warning('Broker quantity changed for engine-owned %s; new entries halted for review',symbol)
    return parsed,orders
