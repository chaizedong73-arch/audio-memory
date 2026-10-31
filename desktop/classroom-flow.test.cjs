const test=require('node:test');const assert=require('node:assert/strict');const {createClassroomFlow}=require('./classroom-flow.cjs');
function fixture() {
 const events=[];let mode=false;const states={gateway:false,visual:false,context:false,camera:false,recording:false};
 const services=Object.fromEntries(Object.keys(states).map(name=>[name,{isOwned:()=>states[name],start:async()=>{events.push('start:'+name);states[name]=true;return {status:'owned'}},stop:async()=>{events.push('stop:'+name);states[name]=false;return {status:'stopped'}}}]));
 const flow=createClassroomFlow({services,setMode:async enabled=>{events.push('mode:'+enabled);mode=enabled;}});
 return {flow,services,states,events,mode:()=>mode};
}
test('classroom starts sequentially and stops only its own services',async()=>{
 const f=fixture();f.states.gateway=true;
 assert.equal((await f.flow.start()).status,'active');assert.equal(f.mode(),true);
 assert.deepEqual(f.events,['mode:true','start:visual','start:context','start:camera','start:recording']);
 assert.equal((await f.flow.stop()).status,'stopped');assert.equal(f.mode(),false);assert.equal(f.states.gateway,true);
 assert.deepEqual(f.events.slice(5),['stop:recording','stop:camera','stop:context','stop:visual','mode:false']);
});
test('partial startup reports failure and still stops started services',async()=>{
 const f=fixture();f.services.recording.start=async()=>({status:'error',message:'设备不可用'});
 const result=await f.flow.start();assert.equal(result.status,'partial');assert.deepEqual(result.errors,[{name:'recording',message:'设备不可用'}]);
 assert.equal((await f.flow.stop()).status,'stopped');assert.equal(f.mode(),false);
});
test('failed stop retains active state and retries only unfinished service',async()=>{
 const f=fixture();await f.flow.start();const stop=f.services.recording.stop;f.services.recording.stop=async()=>({status:'error'});
 assert.equal((await f.flow.stop()).status,'partial');assert.equal(f.flow.isActive(),true);
 f.services.recording.stop=stop;assert.equal((await f.flow.stop()).status,'stopped');assert.equal(f.mode(),false);
});
test('does not disable classroom mode previously enabled elsewhere',async()=>{
 let mode=true;const events=[];const service={isOwned:()=>true,start:async()=>({status:'owned'}),stop:async()=>({status:'stopped'})};
 const flow=createClassroomFlow({services:Object.fromEntries(['gateway','visual','context','camera','recording'].map(x=>[x,service])),readMode:async()=>mode,setMode:async enabled=>{events.push(enabled);mode=enabled}});
 assert.equal((await flow.start()).status,'active');assert.equal((await flow.stop()).status,'stopped');assert.equal(mode,true);assert.deepEqual(events,[]);
});
