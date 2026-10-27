"""Honest point-in-time replay of supplied strategy trades and archived AI decisions.
No model is called. No historical fundamentals/news/AI decisions are fabricated.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

def stamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('All replay timestamps must include a timezone')
    return result

def permitted(trade,variant):
    entry=stamp(trade['entry_time'])
    if stamp(trade['signal_time'])>entry:raise ValueError('Signal look-ahead detected')
    if variant=='A':return True
    evidence=trade.get('premarket_decision')
    if not evidence or stamp(evidence['observed_at'])>entry or evidence['action']!='BUY':return False
    if stamp(evidence['data_as_of'])>stamp(evidence['observed_at']):raise ValueError('Research look-ahead detected')
    if variant=='B':return True
    decision=trade.get('entry_decision')
    if not decision or stamp(decision['observed_at'])>entry or decision['action']!='BUY':return False
    if stamp(decision['data_as_of'])>stamp(decision['observed_at']):raise ValueError('Validation look-ahead detected')
    # D only adds advisory reviews; recommendations do not invent historical exits.
    return True

def replay(trades,marks,initial,variant,max_positions=3):
    selected=[t for t in trades if permitted(t,variant)]
    events=[]
    for t in selected:
        if not 0<float(t['qty']) or not 0<float(t['entry_fill']) or not 0<float(t['exit_fill']):raise ValueError('Actual or PIT simulated fills required')
        start,end=stamp(t['entry_time']),stamp(t['exit_time'])
        if end<=start:raise ValueError('Invalid holding period')
        events.extend([(start,1,t),(end,0,t)])
    events+= [(stamp(m['timestamp']),2,m) for m in marks]
    events.sort(key=lambda v:(v[0],v[1]))
    cash=float(initial);positions={};prices={};equity=[];closed=[];turnover=0.;fees=0.;slippage=0.;approved=set()
    for when,kind,event in events:
        if kind==2:
            prices.update(event['prices'])
            if any(symbol not in prices for symbol in positions):raise ValueError('Missing point-in-time position marks')
            value=cash+sum((float(prices[s])*p['qty'] if p['side']=='long' else -float(prices[s])*p['qty']) for s,p in positions.items())
            equity.append((when,value));continue
        symbol=event['ticker'];qty=float(event['qty']);side=event.get('side','long');direction=1 if side=='long' else -1
        fill=float(event['entry_fill'] if kind==1 else event['exit_fill']);fee=float(event.get('entry_fee' if kind==1 else 'exit_fee',0))
        if kind==1:
            if symbol in positions or len(positions)>=max_positions or qty*fill>cash:continue
            cash-=direction*qty*fill+fee;positions[symbol]=dict(qty=qty,side=side,trade=event)
            prices[symbol]=fill;approved.add(event['id'])
        elif event['id'] in approved and symbol in positions:
            cash+=direction*qty*fill-fee;positions.pop(symbol)
            pnl=direction*qty*(fill-float(event['entry_fill']))-float(event.get('entry_fee',0))-fee
            closed.append(dict(pnl=pnl,days=(when-stamp(event['entry_time'])).total_seconds()/86400))
            prices[symbol]=fill
        else:continue
        turnover+=qty*fill;fees+=fee;slippage+=float(event.get('entry_slippage_cost' if kind==1 else 'exit_slippage_cost',0))
    if positions:raise ValueError('Replay window has unclosed trades; supply terminal marks and explicit exits or a complete window')
    if not equity:raise ValueError('Daily point-in-time portfolio marks required')
    # One mark per daily session is required by the caller, including flat days.
    values=[float(initial)]+[v for _,v in equity]
    if any(v<=0 for v in values):raise ValueError('Nonpositive equity; risk/return metrics undefined')
    returns=[b/a-1 for a,b in zip(values,values[1:])]
    peak=values[0];drawdown=0
    for value in values:peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
    total=cash/initial-1;days=(equity[-1][0]-equity[0][0]).days
    gains=[t['pnl'] for t in closed if t['pnl']>0];losses=[t['pnl'] for t in closed if t['pnl']<0]
    sharpe=statistics.mean(returns)/statistics.stdev(returns)*math.sqrt(252) if len(returns)>2 and statistics.stdev(returns)>0 else None
    return dict(total_return=total,annualized_return=(1+total)**(365.25/days)-1 if days>=365 else None,
        maximum_drawdown=drawdown,sharpe=sharpe,profit_factor=sum(gains)/abs(sum(losses)) if losses else None,
        win_rate=len(gains)/len(closed) if closed else None,average_gain=statistics.mean(gains) if gains else None,
        average_loss=statistics.mean(losses) if losses else None,trade_count=len(closed),turnover=turnover/initial,
        commissions=fees,spread_slippage_cost=slippage,average_holding_days=statistics.mean(t['days'] for t in closed) if closed else None,
        ai_cost=sum(float(t.get('ai_cost',0)) for t in trades) if variant!='A' else 0,
        ai_calls=sum(int(t.get('ai_calls',0)) for t in trades) if variant!='A' else 0)

def compare(data):
    if not data.get('point_in_time_attested'):raise ValueError('PIT source/constituent/evidence attestation required')
    if not data.get('benchmark_prices'):raise ValueError('Point-in-time benchmark series required')
    trades=data['trades'];marks=data['daily_marks'];initial=float(data.get('initial_equity',10000))
    if len({t['id'] for t in trades})!=len(trades):raise ValueError('Duplicate replay trade IDs')
    if not math.isfinite(initial) or initial<=0:raise ValueError('Invalid initial equity')
    benchmark=data['benchmark_prices'];benchmark_return=float(benchmark[-1]['price'])/float(benchmark[0]['price'])-1
    output={v:replay(trades,marks,initial,v) for v in 'ABCD'}
    phases={'A':set(),'B':{'premarket'},'C':{'premarket','entry'},'D':{'premarket','entry','postmarket'}}
    for variant,row in output.items():
        if 'ai_usage' in data:
            usage=[u for u in data['ai_usage'] if u['task'] in phases[variant]]
            row['ai_calls']=len(usage);row['ai_cost']=sum(float(u['cost']) for u in usage)
        row['benchmark_relative_return']=row['total_return']-benchmark_return
        row['return_after_ai_cost']=row['total_return']-row['ai_cost']/initial
    windows=[]
    for window in data.get('walk_forward_windows',[]):
        train_end=stamp(window['train_end']);start=stamp(window['test_start']);end=stamp(window['test_end'])
        if not train_end<start<end:raise ValueError('Walk-forward windows overlap training/future')
        test=[t for t in trades if start<=stamp(t['entry_time']) and stamp(t['exit_time'])<=end]
        test_marks=[m for m in marks if start<=stamp(m['timestamp'])<=end]
        windows.append(dict(window=window,results={v:replay(test,test_marks,initial,v) for v in 'ABCD'}))
    return dict(comparisons=output,walk_forward=windows,limitations=[
        'Uses supplied deterministic strategy opportunities, fills, daily marks and archived PIT decisions; it is not a historical news/LLM generator.',
        'Unrecorded AI decisions cannot qualify AI variants. Survivorship and source PIT correctness require the supplied attestation.',
        'D preserves C execution; postmarket recommendations are advisory, so no untested AI-driven exits are invented.',
        'Daily-mark Sharpe uses 252 sessions; annualization is omitted for windows shorter than one year.'])
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input');args=parser.parse_args()
    print(json.dumps(compare(json.loads(Path(args.input).read_text())),indent=2,allow_nan=False))
