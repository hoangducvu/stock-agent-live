"""Read-only explanations of screening coverage and paid company-research outcomes."""
import json
from datetime import datetime, timezone
from .calendar import ET


def research_diagnostics(db, scope, model, day):
    key=scope+':'+day
    universe=db.get('universe',key)
    selection=db.get('universe_selection',key) or {}
    progress=db.get('scan_progress',key)
    screening=db.get('premarket_screening',key) or db.get('screening',key) or {}
    technical=db.get('technical_screening',key)
    prefix=scope+':'+model+':'
    results={}
    # Do not expire audit history or infer discarded response contents.
    with db.connect() as connection:
        for row in connection.execute("SELECT key,payload FROM objects WHERE kind='company_result'"):
            if row['key'].startswith(prefix) and row['key'].endswith(':'+day):
                payload=json.loads(row['payload']);results[payload['ticker']]=payload
        # Old versions recorded only the exception type. Show this limitation
        # explicitly, with the usage ledger joined to the company ticker.
        for row in connection.execute("SELECT ts,key,payload FROM events WHERE kind='company_research_failure' ORDER BY ts"):
            if not row['key'].startswith(prefix):continue
            event_day=datetime.fromtimestamp(row['ts'],timezone.utc).astimezone(ET).date().isoformat()
            ticker=row['key'][len(prefix):]
            if event_day!=day or ticker in results:continue
            event=json.loads(row['payload']);ledger={}
            attempt=connection.execute("SELECT ts FROM objects WHERE kind='company_attempt' AND key=?",(row['key']+':'+day,)).fetchone()
            if attempt:
                for usage in connection.execute("SELECT o.payload FROM objects o JOIN usage u ON o.key=u.id WHERE o.kind='search_usage' AND u.ts BETWEEN ? AND ?",(attempt['ts']-1,attempt['ts'])):
                    payload=json.loads(usage['payload'])
                    if payload.get('ticker')==ticker and payload.get('day')==day:ledger=payload
            results[ticker]=dict(ticker=ticker,day=day,status='rejected',cost=ledger.get('cost'),searches=ledger.get('searches'),
                reason=event.get('reason') or dict(code='legacy_validation_reason_unavailable',
                    message='This older attempt recorded only '+event.get('type','an exception')+'; the response and exact validation reason were not saved.',details={}))
    import config
    core=list(config.STOCK_UNIVERSE)
    coverage=dict(available=universe is not None,count=len(universe or []),policy=selection.get('policy','legacy_universe'),
                  first_symbol=universe[0] if universe else None,last_symbol=universe[-1] if universe else None,
                  core_included=[s for s in core if universe is not None and s in universe],
                  core_not_scanned=[s for s in core if universe is not None and s not in universe])
    messages=[]
    if coverage['core_not_scanned']:
        suffix=('The broker did not return them as active, tradable US equities.' if selection.get('policy')=='all_active_tradable_us_equities' else
                'They were outside the saved research universe, so no screening verdict exists for them.')
        messages.append('Core watchlist symbols not scanned: '+', '.join(coverage['core_not_scanned'])+'. '+suffix)
    if selection.get('policy')=='all_active_tradable_us_equities':
        messages.append('All active, tradable US equities returned by Alpaca are included. No alphabetical cutoff or exchange whitelist is applied. Technical filters rank the shortlist before paid AI research.')
    elif universe and universe==sorted(universe) and not technical:
        messages.append('The saved universe is alphabetically ordered. The historical default capped the sorted asset list before screening.')
    if progress and progress.get('status')=='failed':
        messages.append('The market-data scan did not finish. No partial-universe shortlist was submitted to AI.')
    if technical:
        shortlist=[{k:r.get(k) for k in ('ticker','score','price','return_20d','relative_strength','rsi','average_dollar_volume')} for r in technical.get('candidates',[])]
    else:
        # Only recover the shortlist from stored records; never regenerate
        # historical rankings with current prices or thresholds.
        shortlist=[]
        for ticker in results:
            with db.connect() as connection:
                saved=connection.execute("SELECT ts,payload FROM objects WHERE kind='screened' AND key=?",(scope+':'+ticker,)).fetchone()
            record=json.loads(saved['payload']) if saved else None
            recorded_day=datetime.fromtimestamp(saved['ts'],timezone.utc).astimezone(ET).date().isoformat() if saved else None
            if record and recorded_day==day:
                shortlist.append({k:record.get(k) for k in ('ticker','score','price','return_20d','relative_strength','rsi','average_dollar_volume')})
        shortlist.sort(key=lambda r:-(r.get('score') or 0))
    return dict(coverage=coverage,messages=messages,shortlist=shortlist,
                company_results=list(results.values()),screening=screening,
                technical_screening=technical,scan_progress=progress,selection_rule='Technical score = relative return versus SPY × 100 + min(20-day return × 100, 20) + (price / 200-day average − 1) × 10 − ATR/price × 100. Highest scores across the complete scanned universe receive the limited research slots; ties use ticker order.')


def empty_summary(diagnostic):
    outcomes=diagnostic['company_results']
    failed=[r for r in outcomes if r['status'] in {'rejected','provider_failed'}]
    if failed:
        reasons='; '.join(r['ticker']+': '+r['reason']['message'] for r in failed)
        return f'No evidence-complete candidates. {len(failed)} company-research attempts failed. {reasons} Final AI ranking was skipped.'
    return 'No candidates passed the screening and evidence requirements; final AI ranking was skipped.'
