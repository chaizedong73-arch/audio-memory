const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const os=require('node:os');const {removeFixture}=require('./test-fixtures.cjs');const {createServiceController}=require('./service-controller.cjs');
test('context worker starts once, registers, waits without audio, and stops',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-context-worker-'));const options={root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'registry'),kind:'context'};
 const first=createServiceController(options),second=createServiceController(options);
 try {const started=await first.start();assert.equal(started.status,'owned',started.message);
  const duplicate=await second.start();assert.equal(duplicate.status,'error');
  let state;for(let i=0;i<30;i++){try{state=JSON.parse(await fs.readFile(path.join(root,'out','context-auto','state.json'),'utf8'));if(state.status==='waiting')break}catch{}await new Promise(r=>setTimeout(r,100))}
  assert.equal(state.status,'waiting');assert.equal((await first.stop()).status,'stopped');
  const registry=JSON.parse(await fs.readFile(path.join(root,'registry','process-registry.json'),'utf8'));assert.ok(registry.processes.every(p=>p.status==='exited'));
 }finally{if(second.isOwned())await second.stop();if(first.isOwned())await first.stop();await removeFixture(root)}
});
