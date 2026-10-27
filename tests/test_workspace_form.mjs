// Exercise the actual submit handler with disabled-input FormData semantics.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../dist/workspace.js',import.meta.url),'utf8');
const start=source.indexOf("$('settings-form').addEventListener('submit',");
const end=source.indexOf("\n$('check').onclick",start);
assert(start>=0&&end>start);
let handler, pending, sent;
const inputs=[['api_key','new-paper-key'],['secret_key','new-matching-secret'],['strategies','orb'],['strategies','news'],['news_enabled','on'],['slack_notifications','on'],['slack_channel','#trades'],['slack_webhook','https://hooks.slack.com/services/TEST/ONLY/FAKE'],['allocation_mode','fill_slots'],['buying_power_reserve_pct','5'],['max_gross_exposure_pct','400'],['entry_start','09:30'],['ai_premarket_time','07:00'],['opening_delay_minutes','0'],['ai_daily_budget','10'],['ai_research_slots','20'],['max_order_value','10000'],['position_size_multiplier','10'],['max_position_pct','5'],['max_daily_loss_pct','2'],['max_positions','3'],['starting_capital','5000'],['halt_equity','4500']].map(([name,value])=>({name,value,disabled:false}));
const form={elements:Object.fromEntries(inputs.map(i=>[i.name,i])),addEventListener:(name,callback)=>handler=callback};
class BrowserFormData{
 constructor(target){this.rows=inputs.filter(i=>!i.disabled).map(i=>[i.name,i.value]);}
 getAll(name){return this.rows.filter(r=>r[0]===name).map(r=>r[1]);}
 has(name){return this.rows.some(r=>r[0]===name);}
 [Symbol.iterator](){return this.rows[Symbol.iterator]();}
}
const context={FormData:BrowserFormData,$:()=>form,notice:()=>{},ready:true,
 action:fn=>{inputs.forEach(i=>i.disabled=true);pending=fn();},
 api:async(path,options)=>{sent=JSON.parse(options.body);},
 loadSettings:async()=>{},checkReadiness:async()=>{}};
vm.runInNewContext(source.slice(start,end),context);
handler({preventDefault(){},target:form});
await pending;
assert.equal(sent.api_key,'new-paper-key');
assert.equal(sent.secret_key,'new-matching-secret');
assert.deepEqual(sent.strategies,['orb','news']);
assert.equal(sent.entry_start,'09:30');
assert.equal(sent.ai_premarket_time,'07:00');
assert.equal(sent.opening_delay_minutes,0);
assert.equal(sent.ai_daily_budget,10);
assert.equal(sent.ai_research_slots,20);
assert.equal(sent.max_position_pct,5);
assert.equal(sent.max_order_value,10000);
assert.equal(sent.position_size_multiplier,10);
assert.equal(sent.allocation_mode,'fill_slots');
assert.equal(sent.buying_power_reserve_pct,5);
assert.equal(sent.max_gross_exposure_pct,400);
assert.equal(sent.shorts_enabled,false);
assert.equal(sent.news_enabled,true);
assert.equal(sent.slack_notifications,true);
assert.equal(sent.slack_channel,'#trades');
assert.equal(sent.slack_webhook,'https://hooks.slack.com/services/TEST/ONLY/FAKE');
console.log('Actual settings form: key rotation, checkboxes, risk values and disabled-input ordering passed.');
