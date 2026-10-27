import {drawEquityChart} from './equity-chart.js';

// Retire the previous dashboard's browser-stored broker credentials.
try { localStorage.removeItem('stockagent_auth'); } catch {}
const $ = id => document.getElementById(id);
let settings = {}, running = false, ready = false, busy = false, pollBusy = false;
let summaryAttemptAt=0;
let accountSnapshot=null,equityHistory=null,historyAttemptAt=0,historyRequest=0,snapshotRequest=0,statusRequest=0,lastResearchRefresh=0;
const descriptions = {
  ema_vwap:['EMA + VWAP Momentum','Intraday momentum using five-minute bars, trend confirmation, and ATR-based stops.'],
  orb:['Opening Range Breakout','Breakouts above the first 30-minute range, with a daily trend filter and ATR-based stops.'],
  rsi:['RSI Bounce','Daily swing strategy: RSI(7) below 25 near the lower Bollinger Band; exits above RSI 55.']
};
const money = n => n == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(n));
function notice(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);$('notice').hidden=false;}
async function api(path,options={}){
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),120000);
  try {
    const r=await fetch('/api/'+path,{...options,credentials:'same-origin',headers:{'Content-Type':'application/json',...options.headers},signal:controller.signal,cache:'no-store'});
    let data;try{data=await r.json();}catch{throw new Error('Server returned an unexpected response. Retry in a moment.');}
    if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
    return data;
  } catch(e){if(e.name==='AbortError')throw new Error('Request timed out. Refresh engine status before trying again.');throw e;}finally{clearTimeout(timer);}
}
function tab(name){if(!['overview','readiness','settings','research'].includes(name))name='overview';document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!==name);document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.tab===name));$('breadcrumb').textContent=name[0].toUpperCase()+name.slice(1);history.replaceState(null,'','#'+name);}
document.querySelectorAll('[data-tab],[data-open]').forEach(el=>el.addEventListener('click',()=>tab(el.dataset.tab||el.dataset.open)));
function controls(){ $('start').disabled=busy||running||!ready;$('stop').disabled=busy||!running;$('save').disabled=busy||running;document.querySelectorAll('#settings-form input,#settings-form select').forEach(el=>el.disabled=running||busy);$('select-all').disabled=busy||running;$('clear-strategies').disabled=busy||running;$('test-slack').disabled=busy;$('check').disabled=busy;$('refresh').disabled=busy;aiControls(); }
let catalog = [], aiModels = [];
async function loadSettings(){
  const priorAccount=settings.paper_account_id;
  [settings,catalog,aiModels]=await Promise.all([api('workspace/settings'),api('workspace/strategies'),api('workspace/ai-models')]);
  if(priorAccount!==settings.paper_account_id)resetAccountView();
  const form=$('settings-form');
  for(const [k,v] of Object.entries(settings)){
    if(['api_key','secret_key','strategies','shorts_enabled','news_enabled','slack_notifications','slack_channel','slack_webhook'].includes(k))continue;
    if(form.elements[k])form.elements[k].value=v;
  }
  form.elements.shorts_enabled.checked=settings.shorts_enabled;
  form.elements.news_enabled.checked=settings.news_enabled;
  form.elements.slack_notifications.checked=settings.slack_notifications;
  form.elements.slack_channel.value=settings.slack_channel||'';
  $('slack-status').textContent=settings.slack_configured?'WEBHOOK SAVED':'NOT CONNECTED';
  const aiForm=$('ai-settings-form');
  aiForm.elements.ai_model.replaceChildren();
  for(const model of aiModels){const option=document.createElement('option');option.value=model.id;option.textContent=model.name;aiForm.elements.ai_model.append(option);}
  aiForm.elements.ai_model.value=settings.ai_model;showModelCost();
  aiForm.elements.ai_enabled.checked=Boolean(settings.ai_enabled&&settings.ai_configured);
  $('ai-key-status').textContent=settings.ai_enabled&&settings.ai_configured?'ENABLED':settings.ai_configured?'KEY SAVED · DISABLED':'DISABLED';
  $('ai-key-hint').textContent=settings.ai_configured?'A key is saved and hidden. Leave this field blank to keep it, or use Remove key to disable and delete it.':'No AI key saved. AI is disabled; the original trading algorithm remains available.';
  aiControls();
  form.querySelectorAll('[name="strategies"]').forEach(el=>el.checked=settings.strategies.includes(el.value));
  $('setup').hidden=settings.credentials_saved;
  $('saved-badge').textContent=settings.credentials_saved?'KEYS SAVED':'NOT CONNECTED';
  $('key-hint').textContent=settings.credentials_saved?'Saved keys are hidden. To rotate keys, enter BOTH the new API key and its matching secret. Stop the engine first.':'Enter both keys from the same Alpaca paper account. Keys are encrypted and never returned to this page.';
  $('strategy-name').textContent=settings.strategies.length+' enabled strategies';
  $('strategy-description').textContent=catalog.filter(s=>settings.strategies.includes(s.id)).map(s=>s.name).join(' · ');
  $('position-budget').textContent=settings.position_size_multiplier>1?settings.position_size_multiplier+'× normal allocation':settings.allocation_mode==='fill_slots'?'Buying power across '+settings.max_positions+' slots':settings.max_position_pct+'% of buying power';
  $('daily-limit').textContent=settings.max_daily_loss_pct+'%';$('order-cap').textContent=money(settings.max_order_value);
}

function drawPositions(rows){const tbody=$('positions');tbody.replaceChildren();$('positions-count').textContent=rows.length;if(!rows.length){const tr=tbody.insertRow(),td=tr.insertCell();td.colSpan=4;td.className='empty';td.textContent='No open positions in this paper account.';}for(const p of rows){const tr=tbody.insertRow();for(const v of [p.symbol,p.qty,money(p.market_value),money(p.unrealized_pl)])tr.insertCell().textContent=v;}}
async function checkReadiness(){ready=false;controls();$('readiness-title').textContent='Checking broker access…';const result=await api('workspace/readiness');ready=result.ready;$('checks').replaceChildren();for(const c of result.checks){const row=document.createElement('div');row.className='check-row';const mark=document.createElement('span');mark.className='check-mark'+(c.ok?'':' fail');mark.textContent=c.ok?'✓':'!';const body=document.createElement('div'),label=document.createElement('strong'),detail=document.createElement('p');label.textContent=c.label;detail.textContent=c.detail;body.append(label,detail);row.append(mark,body);$('checks').append(row);}$('readiness-title').textContent=ready?'Preflight checks passed':'Action needed before starting';$('readiness-summary').textContent=ready?'Paper engine can start and wait for the next trading session.':'Open Readiness to review the checks.';$('equity').textContent=money(result.account.equity);$('buying-power').textContent=money(result.account.buying_power);drawPositions(result.positions);$('market-status').textContent=result.clock.is_open?'MARKET OPEN':'MARKET CLOSED';$('next-session').textContent=result.clock.is_open?'The market is open':result.clock.next_open?new Date(result.clock.next_open).toLocaleString(undefined,{weekday:'short',hour:'2-digit',minute:'2-digit',timeZoneName:'short'}):'Broker not connected';$('session-detail').textContent=result.clock.next_open?'Broker next open: '+new Date(result.clock.next_open).toLocaleString()+'. Trading follows the broker calendar.':'Save valid paper credentials in Settings to check the session.';controls();return result;}
async function loadStatus(){const request=++statusRequest,s=await api('workspace/status');if(request!==statusRequest)return;running=s.running;$('engine').textContent=running?'Running':'Stopped';$('engine-detail').textContent=running?'Paper engine active · '+(s.enabled_strategies?.length||0)+' enabled strategies':'No automatic trading restart';$('logs').textContent=s.logs?.length?s.logs.join('\n'):'No engine activity yet. Start submits paper orders when the strategy finds a signal during market hours.';controls();}

async function loadDailySummary(force=false){
  if(!settings.credentials_saved||(!force&&Date.now()-summaryAttemptAt<60000))return;
  summaryAttemptAt=Date.now();const account=settings.paper_account_id;
  try{
    const result=await api('workspace/daily-summary');
    if(account!==settings.paper_account_id)return;
    const report=result.report;
    if(!report){$('daily-summary').textContent=result.detail;return;}
    if(report.account_id!==account)return;
    $('summary-date').textContent=report.date+' · Current paper account · Eastern Time';
    $('daily-summary').textContent='Closing equity '+money(report.closing_equity)+' · Account P&L '+money(report.account_pnl)+' · '+report.filled_orders+' filled orders · '+report.fills+' fills · Buy volume '+money(report.buy_volume)+' · Sell volume '+money(report.sell_volume);
    $('summary-detail').textContent=report.detail+' Reports follow the currently connected paper account. Changing accounts changes the displayed history.';
  }catch(error){if(account===settings.paper_account_id)$('summary-detail').textContent='Summary refresh unavailable. '+error.message;}
}

function resetAccountView(){
  summaryAttemptAt=0;$('daily-summary').textContent='Waiting for the selected account…';$('summary-date').textContent='Latest completed session';$('summary-detail').textContent='Available five minutes after the exchange closes, including early-close days.';
  accountSnapshot=null;equityHistory=null;historyAttemptAt=0;historyRequest++;snapshotRequest++;
  for(const id of ['equity','buying-power','positions-count','chart-equity'])$(id).textContent='—';
  $('cash-balance').textContent='Cash + market value of holdings';
  $('chart-change').textContent='Waiting for account history';$('chart-hover').textContent='';
  $('equity-chart').replaceChildren();$('equity-chart').setAttribute('hidden','');
  $('chart-status').textContent=settings.credentials_saved?'Loading the selected account…':'Connect your paper account to load its balance history.';
  $('account-sync').textContent=settings.credentials_saved?'Connecting to the selected account…':'Connect an account for live updates';$('account-sync').dataset.stale='true';
  $('orders-count').textContent='Latest 50 · Updates automatically';
  for(const [id,columns] of [['positions',4],['orders',6]]){
    const body=$(id);body.replaceChildren();const cell=body.insertRow().insertCell();cell.colSpan=columns;cell.className='empty';
    cell.textContent=settings.credentials_saved?'Waiting for the selected account…':'Connect your account to load broker data.';
  }
}

function drawOrders(rows){
  const body=$('orders');body.replaceChildren();$('orders-count').textContent=`${rows.length} recent orders · Updates every 5 seconds`;
  if(!rows.length){const cell=body.insertRow().insertCell();cell.colSpan=6;cell.className='empty';cell.textContent='No recent orders in this paper account.';return;}
  for(const order of rows){
    const row=body.insertRow();
    const quantity=order.qty!=null?`${order.qty} / ${order.filled_qty??'0'}`:order.notional!=null?`${money(order.notional)} notional / ${order.filled_qty??'0'} filled`:'—';
    const time=order.submitted_at?new Date(order.submitted_at).toLocaleString():'—';
    for(const value of [order.symbol,order.side,quantity,money(order.filled_avg_price),(order.status||'unknown').replaceAll('_',' '),time])row.insertCell().textContent=value??'—';
    row.cells[4].className='order-state';row.cells[4].dataset.state=order.status||'unknown';
  }
}

async function loadAccountSnapshot(){
  if(!settings.credentials_saved)return;
  const account=settings.paper_account_id,request=++snapshotRequest;
  try{
    const snapshot=await api('workspace/account-snapshot');
    if(request!==snapshotRequest||account!==settings.paper_account_id||snapshot.account_id!==account)return;
    accountSnapshot=snapshot;
    $('equity').textContent=money(snapshot.account.equity);$('buying-power').textContent=money(snapshot.account.buying_power);
    $('cash-balance').textContent='Cash '+money(snapshot.account.cash);
    drawPositions(snapshot.positions);drawOrders(snapshot.orders);
    $('market-status').textContent=snapshot.clock.is_open?'MARKET OPEN':'MARKET CLOSED';
    $('next-session').textContent=snapshot.clock.is_open?'The market is open':snapshot.clock.next_open?new Date(snapshot.clock.next_open).toLocaleString(undefined,{weekday:'short',hour:'2-digit',minute:'2-digit',timeZoneName:'short'}):'Session unavailable';
    $('account-sync').textContent='Live · Updated '+new Date(snapshot.updated_at).toLocaleTimeString();$('account-sync').dataset.stale='false';
    renderEquity();return snapshot;
  }catch(error){
    if(request!==snapshotRequest||account!==settings.paper_account_id)return;
    $('account-sync').textContent='Live updates unavailable · Displayed data may be outdated';$('account-sync').dataset.stale='true';
    throw error;
  }
}

function renderEquity(){
  const points=[...(equityHistory?.points||[])];
  const live=accountSnapshot?.account?.equity;
  const timestamp=Date.parse(accountSnapshot?.updated_at)/1000;
  if(live!=null&&Number.isFinite(Number(live))&&Number.isFinite(timestamp)&&timestamp>=(points.at(-1)?.timestamp||0))points.push({timestamp,equity:Number(live)});
  const chart=drawEquityChart($('equity-chart'),$('chart-hover'),points,$('equity-period').value);
  if(!chart.points.length){$('chart-equity').textContent='—';$('chart-change').textContent='No equity observations available';return;}
  const first=chart.points[0].equity,last=chart.points.at(-1).equity,change=last-first;
  $('chart-equity').textContent=money(last);
  $('equity-chart').closest('.equity-panel').dataset.direction=change<0?'negative':'positive';
  const percent=first!==0?' ('+(change>=0?'+':'')+(change/Math.abs(first)*100).toFixed(2)+'%)':'';
  $('chart-change').textContent=chart.points.length<2?'Current account snapshot':(change>=0?'+':'')+money(change)+percent+' equity change';
}

async function loadEquityHistory(force=false){
  if(!settings.credentials_saved||(!force&&Date.now()-historyAttemptAt<60000))return;
  const account=settings.paper_account_id,period=$('equity-period').value,request=++historyRequest;
  historyAttemptAt=Date.now();
  if(force||!equityHistory)$('chart-status').textContent='Loading account history…';
  try{
    const history=await api('workspace/equity-history?period='+encodeURIComponent(period));
    if(request!==historyRequest||account!==settings.paper_account_id||history.account_id!==account||period!==$('equity-period').value)return;
    equityHistory=history;
    $('chart-status').textContent=history.points.length?'Broker history refreshes every minute · Current equity updates every 5 seconds':'Broker history is not available yet. The current account snapshot is shown when available.';
    renderEquity();
  }catch(error){
    if(request!==historyRequest||account!==settings.paper_account_id)return;
    $('chart-status').textContent='Account history unavailable. '+error.message+' Live account values continue to refresh.';
  }
}

async function refreshWorkspace(){
  if(busy||pollBusy||document.hidden)return;
  pollBusy=true;const wasRunning=running,hasAccount=Boolean(settings.credentials_saved);
  try{
    const tasks=[loadStatus()];
    if(hasAccount)tasks.push(loadAccountSnapshot(),loadEquityHistory(),loadDailySummary());
    if(!$('research').hidden&&Date.now()-lastResearchRefresh>=15000)tasks.push(loadResearch());
    const results=await Promise.allSettled(tasks);
    if(results[0].status==='rejected'){ready=false;$('engine').textContent='Unknown';notice('Engine status unavailable. Broker data refreshes independently.',true);controls();}
    if(hasAccount&&results[1].status==='rejected'){ready=false;controls();}
    if(wasRunning&&!running&&!busy){ready=false;notice('Engine exited. Review the logs, broker positions, and pending orders before restarting.',true);controls();}
  }finally{pollBusy=false;}
}
async function action(fn){if(busy)return;busy=true;controls();try{await fn();}catch(e){ready=false;notice(e.message,true);}finally{busy=false;controls();}}
$('select-all').onclick=()=>{
  const form=$('settings-form');form.querySelectorAll('[name="strategies"]').forEach(el=>el.checked=true);
  form.elements.shorts_enabled.checked=true;form.elements.news_enabled.checked=true;
};
$('clear-strategies').onclick=()=>document.querySelectorAll('[name="strategies"]').forEach(el=>el.checked=false);
$('settings-form').elements.shorts_enabled.onchange=e=>{if(!e.target.checked)document.querySelectorAll('[name="strategies"]').forEach(el=>{if(['ema_vwap_short','rsi_fade'].includes(el.value))el.checked=false;});};
$('settings-form').elements.news_enabled.onchange=e=>{if(!e.target.checked)document.querySelector('[name="strategies"][value="news"]').checked=false;};
$('settings-form').addEventListener('submit',e=>{
  e.preventDefault();
  // Snapshot before action() disables controls: disabled inputs are omitted by FormData.
  const form=e.target, fields=new FormData(form),body={close_on_stop:true,
    strategies:fields.getAll('strategies'), shorts_enabled:fields.has('shorts_enabled'), news_enabled:fields.has('news_enabled'),slack_notifications:fields.has('slack_notifications')};
  for(const [k,v] of fields){
    if(['strategies','shorts_enabled','news_enabled','slack_notifications'].includes(k))continue;
    if(k==='slack_channel'||k==='allocation_mode'){body[k]=v.trim();}
    else if(k==='api_key'||k==='secret_key'||k==='slack_webhook'){if(v.trim())body[k]=v.trim();}
    else body[k]=Number(v);
  }
  if(!body.strategies.length){notice('Select at least one strategy.',true);return;}
  if(Boolean(body.api_key)!==Boolean(body.secret_key)){notice('Enter both the new paper API key and its matching secret, or leave both blank.',true);return;}
  action(async()=>{
    await api('workspace/settings',{method:'PUT',body:JSON.stringify(body)});
    form.elements.api_key.value='';form.elements.secret_key.value='';if(form.elements.slack_webhook)form.elements.slack_webhook.value='';ready=false;
    await loadSettings();notice('Settings and connection saved. Checking the selected paper account…');
    await checkReadiness();
    notice(ready?'Settings saved; paper readiness checks passed.':'Settings saved. Readiness found items to review; open Readiness for the reason.',!ready);
  });
});

$('check').onclick=()=>action(async()=>{await checkReadiness();notice(ready?'Readiness checks passed. No orders were submitted.':'Some checks need attention. Review the details below.',!ready);});
$('refresh').onclick=()=>action(async()=>{await loadStatus();if(settings.credentials_saved){await Promise.all([checkReadiness(),loadAccountSnapshot(),loadEquityHistory(true),loadDailySummary(true)]);}});
$('start').onclick=()=>action(async()=>{if(!confirm('Start the paper engine with your saved settings? It can submit simulated orders during market hours.'))return;await api('workspace/start',{method:'POST'});await loadStatus();notice('Paper engine launched. Watch Engine activity for startup validation and scheduler readiness.');});
$('stop').onclick=()=>action(async()=>{if(!confirm('Stop the paper engine? It will cancel orders and attempt to close positions. Verify the final state in Alpaca.'))return;await api('workspace/stop',{method:'POST'});await loadStatus();await checkReadiness();notice('Engine stopped. Review broker positions and pending orders in Readiness.');});
tab(location.hash.slice(1));
$('equity-period').onchange=()=>{equityHistory=null;historyRequest++;renderEquity();loadEquityHistory(true);};
window.addEventListener('resize',()=>{if(!$('overview').hidden)renderEquity();});
await action(async()=>{await loadSettings();await loadStatus();if(settings.credentials_saved){await Promise.all([checkReadiness(),loadAccountSnapshot(),loadEquityHistory(true),loadDailySummary(true)]);}});
setInterval(refreshWorkspace,5000);
setInterval(()=>{if(settings.credentials_saved&&!busy&&!pollBusy&&!document.hidden&&!$('readiness').hidden)action(checkReadiness);},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshWorkspace();});
window.addEventListener('focus',refreshWorkspace);

async function loadResearch(){
  const research=await api('workspace/research');
  lastResearchRefresh=Date.now();
  $('ai-enabled').textContent=research.enabled?'Enabled':'Disabled';
  $('ai-config').textContent=research.model+' · '+(!research.credentials_configured?'No AI key saved':research.prototype?'Prototype · $'+Number(research.daily_budget).toFixed(2)+'/day estimated budget · up to 6 searches':!research.evidence_configured?'Fundamentals/earnings feed missing':'Provider key saved');
  const schedule=research.schedule;
  if(schedule?.market_open){const local=value=>new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:schedule.timezone}).format(new Date(value));$('ai-schedule-local').textContent=`${schedule.date} · Europe/Malta: Research ${local(schedule.premarket)} · US market opens ${local(schedule.market_open)} · Signal validation from ${local(schedule.entry_validation)} · Review ${local(schedule.postmarket)}. No automatic AI call at the open.`;}else{$('ai-schedule-local').textContent=schedule?.status||'Waiting for exchange calendar';}
  $('ai-calls').textContent=research.usage.calls;$('ai-cost').textContent='$'+Number(research.usage.cost).toFixed(4);
  const rows=Object.values(research.watchlist);$('ai-watch-count').textContent=rows.length;
  $('ai-watchlist').replaceChildren();
  for(const row of rows){const p=document.createElement('p');p.textContent=row.ticker+' · '+money(row.price)+' · '+(row.sector||'Sector unavailable');$('ai-watchlist').append(p);}
  if(!rows.length)$('ai-watchlist').textContent='No approved stocks. Research may be disabled, awaiting evidence, or find no qualifying candidates.';
  $('ai-reports').replaceChildren();
  for(const report of research.reports){const p=document.createElement('p');p.textContent=report.key+' · '+(report.payload.status?report.payload.status+' · ':'')+report.payload.summary;$('ai-reports').append(p);}
  renderResearchDiagnostics(research.diagnostics,$('ai-reports'));
}
function renderResearchDiagnostics(diagnostic,container){
  if(!diagnostic)return;
  const add=text=>{const p=document.createElement('p');p.textContent=text;container.append(p);};
  const coverage=diagnostic.coverage;
  if(coverage?.available)add(`Research universe: ${coverage.count} symbols · ${coverage.first_symbol||'—'} through ${coverage.last_symbol||'—'}. ${diagnostic.technical_screening?.available??diagnostic.screening?.available??0} usable daily summaries.`);
  const progress=diagnostic.scan_progress;
  if(progress)add(`Market-data scan: ${progress.status} · ${progress.processed}/${progress.total} symbols processed · ${progress.available} usable summaries · ${progress.data_rejected} unavailable or invalid · ${progress.held_excluded} already held.`);
  const technical=diagnostic.technical_screening;
  if(technical?.qualified!=null)add(`${technical.qualified} symbols passed technical filters; the top ${technical.shortlist_limit} receive company-research slots, subject to the existing AI budget.`);
  for(const message of diagnostic.messages||[])add(message);
  for(const row of diagnostic.shortlist||[])add(`${row.ticker} · Technical shortlist score ${Number(row.score).toFixed(4)} · 20-day return ${row.return_20d==null?'unavailable':(row.return_20d*100).toFixed(2)+'%'} · versus SPY ${row.relative_strength==null?'unavailable':(row.relative_strength*100).toFixed(2)+' percentage points'}`);
  if(diagnostic.shortlist?.length)add(diagnostic.selection_rule);
  for(const result of diagnostic.company_results||[]){
    const reason=result.reason;
    add(`${result.ticker} · ${result.status} · ${result.searches??'Unknown'} searches · ${result.cost==null?'Charge uncertain':'$'+Number(result.cost).toFixed(4)}${reason?' · '+reason.message:''}`);
    if(reason&&Object.keys(reason.details||{}).length)add(`${result.ticker} · ${reason.code} · ${JSON.stringify(reason.details)}`);
  }
  const core=new Set([...(coverage?.core_included||[]),...(coverage?.core_not_scanned||[])]);
  const rejected=[...(diagnostic.screening?.rejections||[]),...(technical?.rejections||[]).filter(row=>core.has(row.ticker)),...(technical?.data_rejections||[]).filter(row=>core.has(row.ticker)),...(technical?.held_exclusions||[]).filter(row=>core.has(row.ticker))];
  const shown=new Set();
  for(const row of rejected){
    if(shown.has(row.ticker))continue;shown.add(row.ticker);
    add(`${row.ticker} · ${(row.reason_details||[]).map(reason=>reason.message).join(' ')||(row.reasons||[]).join(', ')}`);
  }
}
$('refresh-research').onclick=()=>action(loadResearch);
$('test-slack').onclick=()=>action(async()=>{const result=await api('workspace/notifications/test',{method:'POST'});notice(result.detail);});
await action(loadResearch);

function aiControls(){
  const form=$('ai-settings-form');
  form.elements.ai_api_key.disabled=busy;form.elements.ai_model.disabled=busy;
  const available=Boolean(settings.ai_configured||form.elements.ai_api_key.value.trim());
  form.elements.ai_enabled.disabled=busy||!available;
  if(!available)form.elements.ai_enabled.checked=false;
  $('save-ai').disabled=busy;$('remove-ai').disabled=busy||!settings.ai_configured;
}
$('ai-settings-form').elements.ai_api_key.oninput=aiControls;
$('ai-settings-form').addEventListener('submit',e=>{
  e.preventDefault();const form=e.target,key=form.elements.ai_api_key.value.trim();
  const body={ai_enabled:form.elements.ai_enabled.checked,ai_model:form.elements.ai_model.value};
  if(key)body.ai_api_key=key;
  action(async()=>{
    await api('workspace/settings',{method:'PUT',body:JSON.stringify(body)});
    form.elements.ai_api_key.value='';ready=false;await loadSettings();await loadResearch();
    notice(settings.ai_enabled?'AI preferences saved. Readiness must pass before AI-dependent trading.':'AI preferences saved. AI is disabled.');
  });
});
$('remove-ai').onclick=()=>action(async()=>{
  await api('workspace/settings',{method:'PUT',body:JSON.stringify({ai_api_key:'',ai_enabled:false})});
  $('ai-settings-form').elements.ai_api_key.value='';ready=false;
  await loadSettings();await loadResearch();notice('AI key removed. AI is disabled.');
});

function showModelCost(){
  const selected=aiModels.find(model=>model.id===$('ai-settings-form').elements.ai_model.value);
  if(selected)$('ai-model-cost').textContent=`$${selected.input_per_million} input / $${selected.output_per_million} output per million tokens. Your daily AI budget still applies. Model access depends on your API account.`;
}
$('ai-settings-form').elements.ai_model.onchange=showModelCost;
