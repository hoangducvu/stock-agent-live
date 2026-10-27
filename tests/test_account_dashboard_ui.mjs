import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const chartSource=fs.readFileSync(new URL('../dist/equity-chart.js',import.meta.url),'utf8');
const {equityGeometry,drawEquityChart}=await import('data:text/javascript;base64,'+Buffer.from(chartSource).toString('base64'));
class Element{
  constructor(){this.textContent='';this.dataset={};this.children=[];this.cells=[];this.attributes=new Map();this.value='1M';this.hidden=false;this.clientWidth=600;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];this.cells=[];}
  insertRow(){const row=new Element();this.children.push(row);return row;}
  insertCell(){const cell=new Element();this.cells.push(cell);return cell;}
  setAttribute(name,value){this.attributes.set(name,String(value));}
  removeAttribute(name){this.attributes.delete(name);}
  getBoundingClientRect(){return {left:0,width:600};}
  closest(){return this;}
}
const geometry=equityGeometry([{timestamp:3,equity:5000},{timestamp:1,equity:0},{timestamp:2,equity:null},{timestamp:3,equity:5010},{timestamp:4,equity:NaN},{timestamp:5,equity:-100}]);
assert.deepEqual(geometry.points.map(p=>p.equity),[0,5010,-100]);
assert(!/NaN|Infinity/.test(geometry.path));
assert(!/NaN|Infinity/.test(equityGeometry([{timestamp:1,equity:5000},{timestamp:2,equity:5000}]).path));
assert.equal(equityGeometry([]).path,'');
const svg=new Element(),tooltip=new Element();
svg.setAttribute('hidden','');
const originalDocument=globalThis.document;
globalThis.document={createElementNS:()=>new Element()};
try{
  drawEquityChart(svg,tooltip,[{timestamp:100,equity:5000},{timestamp:200,equity:5100}],'1D');
  assert(!svg.attributes.has('hidden'));
  assert(tooltip.textContent.includes('$5,100.00'));
  svg.onkeydown({key:'ArrowLeft',preventDefault(){}});
  assert(tooltip.textContent.includes('$5,000.00'));
  svg.onpointermove({clientX:600});
  assert(tooltip.textContent.includes('$5,100.00'));
  drawEquityChart(svg,tooltip,[]);
  assert(svg.attributes.has('hidden'));
}finally{globalThis.document=originalDocument;}

const source=fs.readFileSync(new URL('../dist/workspace.js',import.meta.url),'utf8');
const start=source.indexOf('async function loadDailySummary(');
const end=source.indexOf('\nasync function action(',start);
assert(start>=0&&end>start);
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
get('research').hidden=true;
const now=Date.now();
let snapshot={account_id:'account-A',updated_at:new Date(now).toISOString(),account:{equity:'5100',cash:'3000',buying_power:'12000'},positions:[{symbol:'META'}],orders:[{symbol:'META',side:'buy',qty:'2',filled_qty:'2',filled_avg_price:'1050',status:'filled',submitted_at:new Date(now).toISOString()}],clock:{is_open:true}};
const history={account_id:'account-A',period:'1M',points:[{timestamp:now/1000-86400,equity:5000}],updated_at:new Date(now).toISOString()};
const paths=[];let positions=[],researchLoads=0;
const context={$:get,document:{hidden:false},settings:{credentials_saved:true,paper_account_id:'account-A'},
 busy:false,pollBusy:false,running:true,ready:true,accountSnapshot:null,equityHistory:null,historyAttemptAt:0,historyRequest:0,snapshotRequest:0,lastResearchRefresh:0,summaryAttemptAt:0,
 api:async path=>{paths.push(path);if(path==='workspace/daily-summary')return {report:{account_id:'account-A',date:'2026-10-26',closing_equity:5050,account_pnl:50,filled_orders:2,fills:3,buy_volume:1000,sell_volume:1050,detail:'Includes unrealized P&L'}};if(path==='workspace/account-snapshot')return snapshot;if(path.startsWith('workspace/equity-history'))return history;throw Error(path);},
 loadStatus:async()=>{},drawPositions:rows=>positions=rows,money:n=>n==null?'—':'$'+Number(n).toFixed(2),controls:()=>{},notice:()=>{},loadResearch:async()=>researchLoads++,
 drawEquityChart:(_,__,points)=>equityGeometry(points),console};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
await vm.runInContext('refreshWorkspace()',context);
assert.equal(get('equity').textContent,'$5100.00');
assert(get('daily-summary').textContent.includes('Account P&L $50.00'));
assert.equal(get('summary-date').textContent,'2026-10-26 · Current paper account · Eastern Time');
assert.equal(get('buying-power').textContent,'$12000.00');
assert.equal(positions[0].symbol,'META');
assert.equal(get('orders').children[0].cells[4].textContent,'filled');
assert.equal(get('account-sync').dataset.stale,'false');
assert(get('chart-change').textContent.includes('+$100.00'));
const historyRequests=paths.filter(p=>p.includes('equity-history')).length;
snapshot={...snapshot,orders:[{...snapshot.orders[0],status:'partially_filled',filled_qty:'1'}]};
await vm.runInContext('refreshWorkspace()',context);
assert.equal(get('orders').children[0].cells[4].textContent,'partially filled');
assert.equal(paths.filter(p=>p.includes('equity-history')).length,historyRequests,'History is throttled separately from live orders.');
assert.equal(researchLoads,0);

const before=paths.length;
context.document.hidden=true;await vm.runInContext('refreshWorkspace()',context);
context.document.hidden=false;context.busy=true;await vm.runInContext('refreshWorkspace()',context);
context.busy=false;context.pollBusy=true;await vm.runInContext('refreshWorkspace()',context);context.pollBusy=false;
assert.equal(paths.length,before,'Hidden, busy and in-flight refreshes make no requests.');

const lastEquity=get('equity').textContent;
context.api=async()=>{throw Error('Broker unavailable');};
await vm.runInContext('refreshWorkspace()',context);
assert.equal(get('equity').textContent,lastEquity,'Outage preserves the last known balance.');
assert.equal(get('account-sync').dataset.stale,'true');
assert(get('account-sync').textContent.includes('outdated'));

// An old account response cannot repaint a newly selected account.
let finishSnapshot;
context.api=()=>new Promise(resolve=>finishSnapshot=resolve);
const pending=vm.runInContext('loadAccountSnapshot()',context);
context.settings={credentials_saved:true,paper_account_id:'account-B'};
vm.runInContext('resetAccountView()',context);
finishSnapshot(snapshot);await pending;
assert.equal(context.accountSnapshot,null);
assert.equal(get('equity').textContent,'—');

// Changing period while history is in flight discards the old response.
let finishHistory;
context.settings={credentials_saved:true,paper_account_id:'account-A'};
context.api=()=>new Promise(resolve=>finishHistory=resolve);
get('equity-period').value='1M';
const pendingHistory=vm.runInContext('loadEquityHistory(true)',context);
get('equity-period').value='1W';finishHistory(history);await pendingHistory;
assert.equal(context.equityHistory,null);
// A slower old request for the same account cannot rewind a newer balance.
const completions=[];
context.api=()=>new Promise(resolve=>completions.push(resolve));
const older=vm.runInContext('loadAccountSnapshot()',context);
const newer=vm.runInContext('loadAccountSnapshot()',context);
completions[1]({...snapshot,account:{...snapshot.account,equity:'5200'}});await newer;
completions[0](snapshot);await older;
assert.equal(get('equity').textContent,'$5200.00');
// Actual in-flight polling, rather than only a preset guard, cannot overlap.
let finishRefresh,refreshRequests=0;
context.api=()=>{refreshRequests++;return new Promise(resolve=>finishRefresh=resolve);};
context.historyAttemptAt=Date.now();context.summaryAttemptAt=Date.now();
const refreshing=vm.runInContext('refreshWorkspace()',context);
await vm.runInContext('refreshWorkspace()',context);
assert.equal(refreshRequests,1);
finishRefresh(snapshot);await refreshing;
assert.equal(context.pollBusy,false);
assert(source.includes('setInterval(refreshWorkspace,5000)'));
console.log('Account dashboard: chart geometry/keyboard/hover, live orders and balances, throttling, hidden-page pause, outage handling and account/range races passed.');
