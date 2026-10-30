const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/yttv_epg/static/app.js'), 'utf8');
const tick = () => new Promise(setImmediate);
const status = (extra = {}) => ({signed_in:false,session_expired:false,last_refresh:'initial',events:0,all_events:0,hide_spanish:false,xmltv_live_on_air:false,...extra});
function harness(checked=false) {
  const requests=[]; let reloads=0;
  const listeners={};
  const toggle={checked,defaultChecked:checked,addEventListener(name,handler){listeners[name]=handler}};
  const liveListeners={};
  const liveToggle={checked:false,defaultChecked:false,addEventListener(name,handler){liveListeners[name]=handler}};
  const error={textContent:''};
  const context={URL,console,setInterval(){},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},
    window:{location:{reload(){reloads++}},scrollY:0},
    document:{body:{dataset:{signedIn:'false',sessionExpired:'false',lastRefresh:'initial',events:'0',allEvents:'0'}},
      getElementById(id){return id==='hide-spanish'?toggle:id==='xmltv-live-on-air'?liveToggle:id==='auth-error'?error:null},
      querySelectorAll(){return []},querySelector(){return null},addEventListener(){}},
    fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))}};
  vm.createContext(context); vm.runInContext(source,context);
  const respond=(request,data,ok=true)=>request.resolve({ok,json:async()=>data,statusText:'Save failed'});
  return {context,requests,toggle,liveToggle,liveListeners,error,listeners,respond,get reloads(){return reloads},
    run(expression){return vm.runInContext(expression,context)},
    async prime(){respond(requests.shift(),status({hide_spanish:checked}));await tick()}};
}
test('status response cannot reload while a filter save is pending',async()=>{
 const h=harness();await h.prime();const poll=h.run('pollStatus()');const stale=h.requests.shift();
 h.toggle.checked=true;const save=h.run('postFilter({hide_spanish:true}, "Saving")');const request=h.requests.shift();
 h.respond(stale,status({last_refresh:'newer'}));await poll;assert.equal(h.reloads,0);assert.equal(h.toggle.checked,true);
 h.respond(request,{hide_spanish:true,events:0,all_events:0});await save;
 assert.equal(h.run('filterSavePending'),false);
});
test('response started before a completed save cannot reset or reload the checkbox',async()=>{
 const h=harness();await h.prime();const poll=h.run('pollStatus()');const stale=h.requests.shift();
 h.toggle.checked=true;const save=h.run('postFilter({hide_spanish:true}, "Saving")');
 h.respond(h.requests.shift(),{hide_spanish:true});await save;
 h.respond(stale,status({last_refresh:'newer',hide_spanish:false}));await poll;
 assert.equal(h.toggle.checked,true);assert.equal(h.reloads,0);
});
test('failed saves restore the server-confirmed value and expose the error',async()=>{
 const h=harness(true);await h.prime();h.toggle.checked=false;
 const save=h.run('postFilter({hide_spanish:false}, "Saving")');h.respond(h.requests.shift(),{detail:'Save failed'},false);await save;
 assert.equal(h.toggle.checked,true);assert.equal(h.error.textContent,'Save failed');
});
test('network failure restores the saved value and a retry can succeed',async()=>{
 const h=harness();await h.prime();h.toggle.checked=true;
 let save=h.run('postFilter({hide_spanish:true}, "Saving")');h.requests.shift().reject(new Error('Offline'));await save;
 assert.equal(h.toggle.checked,false);assert.equal(h.error.textContent,'Offline');
 h.toggle.checked=true;save=h.run('postFilter({hide_spanish:true}, "Saving")');h.respond(h.requests.shift(),{hide_spanish:true});await save;
 assert.equal(h.toggle.checked,true);
});
test('rapid toggles do not send overlapping saves',async()=>{
 const h=harness();await h.prime();h.toggle.checked=true;h.listeners.change({target:h.toggle});
 const request=h.requests.shift();h.toggle.checked=false;h.listeners.change({target:h.toggle});assert.equal(h.requests.length,0);
 h.respond(request,{hide_spanish:true});await tick();assert.equal(h.toggle.checked,true);
 h.toggle.checked=false;h.listeners.change({target:h.toggle});h.respond(h.requests.shift(),{hide_spanish:false});await tick();assert.equal(h.toggle.checked,false);
});
test('accepted polling detects a preference changed in another tab',async()=>{
 const h=harness();await h.prime();const poll=h.run('pollStatus()');h.respond(h.requests.shift(),status({hide_spanish:true}));await poll;
 assert.equal(h.reloads,1);
});

test('Live toggle ignores stale status and persists the acknowledged value',async()=>{
 const h=harness();await h.prime();const poll=h.run('pollStatus()');const stale=h.requests.shift();
 h.liveToggle.checked=true;h.liveListeners.change({target:h.liveToggle});
 const save=h.requests.shift();assert.equal(JSON.parse(save.options.body).xmltv_live_on_air,true);
 h.respond(save,{xmltv_live_on_air:true});await tick();
 h.respond(stale,status());await poll;
 assert.equal(h.liveToggle.checked,true);assert.equal(h.reloads,0);
});
test('Live toggle rolls back HTTP and network errors and prevents overlapping saves',async()=>{
 const h=harness();await h.prime();
 for(const networkFailure of [false,true]){
  h.liveToggle.checked=true;h.liveListeners.change({target:h.liveToggle});const save=h.requests.shift();
  h.liveToggle.checked=false;h.liveListeners.change({target:h.liveToggle});assert.equal(h.requests.length,0);
  if(networkFailure)save.reject(new Error('Offline'));else h.respond(save,{detail:'Save failed'},false);
  await tick();assert.equal(h.liveToggle.checked,false);assert.ok(h.error.textContent);
 }
});
test('Live preference changed in another tab triggers reload',async()=>{
 const h=harness();await h.prime();const poll=h.run('pollStatus()');
 h.respond(h.requests.shift(),status({xmltv_live_on_air:true}));await poll;assert.equal(h.reloads,1);
});
