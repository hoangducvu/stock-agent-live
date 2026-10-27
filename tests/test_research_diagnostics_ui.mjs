import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../dist/workspace.js',import.meta.url),'utf8');
const start=source.indexOf('function renderResearchDiagnostics(');
const end=source.indexOf("\n$('refresh-research').onclick",start);
assert(start>=0&&end>start);
const rendered=[];
const container={append:p=>rendered.push(p.textContent)};
const context={document:{createElement:()=>({textContent:''})},container};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
context.diagnostic={coverage:{available:true,count:3000,first_symbol:'A',last_symbol:'DYLD',core_not_scanned:['META'],core_included:['AAPL']},
 messages:['META was outside the saved universe.'],
 shortlist:[{ticker:'ACN',score:61.808,return_20d:.4167,relative_strength:.4316}],selection_rule:'Sorted by technical score versus SPY.',
 company_results:[{ticker:'ACN',status:'rejected',searches:2,cost:.0438,reason:{message:'Output limit reached.',code:'incomplete_response',details:{stop_reason:'max_tokens'}}}],
 screening:{available:2506,rejections:[{ticker:'ACN',reason_details:[{message:'No validated financial facts.'}]}]},
 technical_screening:{available:2506,rejections:[{ticker:'AAPL',reason_details:[{message:'RSI 80 is above 75.'}]}]}};
vm.runInContext('renderResearchDiagnostics(diagnostic,container)',context);
const text=rendered.join('\n');
for(const part of ['3000 symbols','2506 usable','META was outside','61.8080','41.67%','43.16 percentage points','max_tokens','$0.0438','RSI 80'])assert(text.includes(part),part);
rendered.length=0;
context.diagnostic.company_results[0].reason.message='<script>untrusted response</script>';
vm.runInContext('renderResearchDiagnostics(diagnostic,container)',context);
assert(rendered.some(text=>text.includes('<script>untrusted response</script>')));
vm.runInContext('renderResearchDiagnostics(undefined,container)',context);
rendered.length=0;
context.diagnostic.scan_progress={status:'scanning',processed:3000,total:12000,available:2700,data_rejected:300,held_excluded:0};
context.diagnostic.technical_screening.qualified=200;
context.diagnostic.technical_screening.shortlist_limit=3;
context.diagnostic.technical_screening.data_rejections=[{ticker:'META',reason_details:[{message:'Only 150 daily bars are available; 201 required.'}]}];
vm.runInContext('renderResearchDiagnostics(diagnostic,container)',context);
assert(rendered.some(text=>text.includes('scanning · 3000/12000 symbols processed')));
assert(rendered.some(text=>text.includes('200 symbols passed technical filters; the top 3')));
assert(rendered.some(text=>text.includes('Only 150 daily bars')));
console.log('Research diagnostics: coverage exclusions, shortlist metrics, exact reasons and text-only rendering passed.');
