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
  const laneListeners = {};
  const laneInput = { defaultValue: "128", value: "128", get valueAsNumber() { return Number(this.value); } };
  const laneStatus = { hidden: true };
  const laneError = { textContent: "" };
  const laneButton = {};
  const lanesUsed = {};
  const laneElements = {
    "lane-count": laneInput,
    "lane-count-form": { addEventListener(name, handler) { laneListeners[name] = handler; } },
    "lane-count-status": laneStatus,
    "lane-count-error": laneError,
    "save-lane-count": laneButton,
    "lanes-used": lanesUsed,
  };
  const context={URL,console,setInterval(){},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},
    window:{location:{reload(){reloads++}},scrollY:0},
    document:{body:{dataset:{signedIn:'false',sessionExpired:'false',lastRefresh:'initial',events:'0',allEvents:'0'}},
      getElementById(id){return id==='hide-spanish'?toggle:id==='xmltv-live-on-air'?liveToggle:id==='auth-error'?error:laneElements[id] ?? null},
      querySelectorAll(){return []},querySelector(){return null},addEventListener(){}},
    fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))}};
  vm.createContext(context); vm.runInContext(source,context);
  const respond=(request,data,ok=true)=>request.resolve({ok,json:async()=>data,statusText:'Save failed'});
  return {context,requests,toggle,liveToggle,liveListeners,error,listeners,respond,get reloads(){return reloads},
    laneInput,laneStatus,laneError,laneButton,lanesUsed,laneListeners,
    run(expression){return vm.runInContext(expression,context)},
    async prime(){respond(requests.shift(),status({hide_spanish:checked}));await tick()}};
}

test("saving a lane count updates the stats and ignores stale polling", async () => {
  const h = harness();
  await h.prime();
  const poll = h.run("pollStatus()");
  const stale = h.requests.shift();
  h.laneInput.value = "160";
  const save = h.laneListeners.submit({ preventDefault() {} });
  const request = h.requests.shift();
  assert.deepEqual(JSON.parse(request.options.body), { lane_count: 160 });
  assert.equal(h.laneButton.disabled, true);
  h.respond(request, { lane_count: 160, lanes_used: 90, dropped: 0 });
  await save;
  h.respond(stale, status({ lane_count: 128 }));
  await poll;
  assert.equal(h.lanesUsed.textContent, "90 / 160");
  assert.match(h.laneStatus.textContent, /Import only the new lanes/);
  assert.equal(h.laneButton.disabled, false);
  assert.equal(h.reloads, 0);
});

test("failed lane count save keeps the draft available for retry", async () => {
  const h = harness();
  await h.prime();
  h.laneInput.value = "64";
  const save = h.laneListeners.submit({ preventDefault() {} });
  h.respond(h.requests.shift(), { detail: "Save failed" }, false);
  await save;
  assert.equal(h.laneError.textContent, "Save failed");
  assert.equal(h.laneStatus.hidden, true);
  assert.equal(h.laneInput.value, "64");
  assert.equal(h.run("boot.laneCount"), 128);
});
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

test('a saved sport or channel change in another tab reloads with unchanged counts', async () => {
  const h = harness();
  await h.prime();

  const poll = h.run('pollStatus()');
  h.respond(h.requests.shift(), status({filter_revision: 'other-tab'}));
  await poll;

  assert.equal(h.reloads, 1);
});

test('the first poll detects filters changed since the dashboard was rendered', async () => {
  const h = harness();
  h.respond(h.requests.shift(), status({filter_revision: 'other-tab'}));
  await tick();

  assert.equal(h.reloads, 1);
});

test('saving filters adopts the server revision and ignores an older poll', async () => {
  const h = harness();
  await h.prime();
  const poll = h.run('pollStatus()');
  const stale = h.requests.shift();

  const save = h.run('postFilter({toggle_channel: "ESPN"}, "Saving")');
  h.respond(h.requests.shift(), {hidden_channels: ['ESPN'], filter_revision: 'saved'});
  await save;
  h.respond(stale, status({filter_revision: 'old'}));
  await poll;

  const current = h.run('pollStatus()');
  h.respond(h.requests.shift(), status({filter_revision: 'saved'}));
  await current;

  assert.equal(h.reloads, 0);
});

test('saving the Live preference triggers a reload so the rendered badges update', async () => {
  const h = harness();
  await h.prime();
  const save = h.run('postFilter({xmltv_live_on_air: true}, "Saving")');
  h.respond(h.requests.shift(), {xmltv_live_on_air: true});
  await save;
  assert.equal(h.liveToggle.checked, true);

  const poll = h.run('pollStatus()');
  h.respond(h.requests.shift(), status({xmltv_live_on_air: true}));
  await poll;

  assert.equal(h.reloads, 1);
});
