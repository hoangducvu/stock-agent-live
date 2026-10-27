import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../dist/workspace.js',import.meta.url),'utf8');
let submit,pending,sent;
const form={elements:{ai_api_key:{value:'private-user-key'},ai_model:{value:'claude-sonnet-4-6'},ai_enabled:{checked:true,disabled:false}},addEventListener:(_,fn)=>submit=fn};
const buttons={'remove-ai':{},'save-ai':{}};
const context={aiModels:[],showModelCost:()=>{},settings:{ai_enabled:true,ai_configured:false},busy:false,ready:true,
 $:id=>id==='ai-settings-form'?form:buttons[id],
 action:fn=>{form.elements.ai_api_key.disabled=true;pending=fn();},
 api:async(_,options)=>{sent=JSON.parse(options.body);},loadSettings:async()=>{},loadResearch:async()=>{},notice:()=>{}};
const start=source.indexOf("$('ai-settings-form').addEventListener('submit',");
const end=source.indexOf("\n$('remove-ai').onclick",start);
assert(start>=0&&end>start);
vm.runInNewContext(source.slice(start,end),context);
submit({preventDefault(){},target:form});await pending;
assert.equal(sent.ai_model,'claude-sonnet-4-6');assert.equal(sent.ai_api_key,'private-user-key');assert.equal(sent.ai_enabled,true);assert.equal(form.elements.ai_api_key.value,'');
form.elements.ai_api_key.value='';form.elements.ai_enabled.checked=false;
submit({preventDefault(){},target:form});await pending;
assert.equal(sent.ai_enabled,false);assert(!Object.hasOwn(sent,'ai_api_key'));
vm.runInNewContext(source.slice(end),context);
buttons['remove-ai'].onclick();await pending;
assert.equal(sent.ai_api_key,'');assert.equal(sent.ai_enabled,false);
const controlsStart=source.indexOf('function aiControls(){');
const controlsEnd=source.indexOf("\n$('ai-settings-form').elements.ai_api_key.oninput",controlsStart);
vm.runInNewContext(source.slice(controlsStart,controlsEnd)+'\naiControls();',context);
assert.equal(form.elements.ai_enabled.disabled,true);assert.equal(form.elements.ai_enabled.checked,false);
console.log('AI settings form: optional key save, blank-field preservation, removal and empty-key disabled state passed.');
