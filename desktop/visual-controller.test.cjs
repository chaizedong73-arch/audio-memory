const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const os=require('node:os');const {removeFixture}=require('./test-fixtures.cjs');const {createServiceController}=require('./service-controller.cjs');
test('visual worker registers, prevents duplicate startup and stops',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-visual-worker-'));const options={root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'registry'),kind:'visual'};
 const first=createServiceController(options),second=createServiceController(options);
 try{const started=await first.start();assert.equal(started.status,'owned',started.message);assert.equal((await second.start()).status,'error');assert.equal((await first.stop()).status,'stopped');const records=JSON.parse(await fs.readFile(path.join(root,'registry','process-registry.json'),'utf8')).processes;assert.ok(records.every(x=>x.status==='exited'));
 }finally{if(second.isOwned())await second.stop();if(first.isOwned())await first.stop();await removeFixture(root)}
});
