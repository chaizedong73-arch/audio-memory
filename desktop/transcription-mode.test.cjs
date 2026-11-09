const test=require('node:test');const assert=require('node:assert/strict');
const {createModeSwitcher}=require('./transcription-mode.cjs');
function fixture(fail=false){let mode='local',owned=true,saved='local';const events=[];
 const controller={isOwned:()=>owned,stop:async()=>{events.push('stop:'+mode);owned=false;return {status:'stopped'};},start:async()=>{events.push('start:'+mode);if(fail&&mode==='cloud')return {status:'error',message:'fixture failure'};owned=true;return {status:'owned'};}};
 return {switch:createModeSwitcher({controller,getMode:()=>mode,setMode:m=>{mode=m;},validate:m=>['local','cloud'].includes(m)?'':'invalid',persist:m=>{saved=m;}}),events,state:()=>({mode,owned,saved})};}
test('running switch drains old audio, starts new worker, and persists selection',async()=>{const f=fixture();assert.equal((await f.switch('cloud')).status,'ready');assert.deepEqual(f.events,['stop:local','start:cloud']);assert.deepEqual(f.state(),{mode:'cloud',owned:true,saved:'cloud'});});
test('failed new worker restores original recording and keeps saved mode',async()=>{const f=fixture(true);assert.equal((await f.switch('cloud')).status,'error');assert.deepEqual(f.events,['stop:local','start:cloud','start:local']);assert.deepEqual(f.state(),{mode:'local',owned:true,saved:'local'});});
test('invalid selection leaves recording untouched',async()=>{const f=fixture();assert.equal((await f.switch('bad')).status,'error');assert.deepEqual(f.events,[]);});
