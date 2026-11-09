const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');
const path=require('node:path');const os=require('node:os');const {removeFixture}=require('./test-fixtures.cjs');
const {createServiceController}=require('./service-controller.cjs');
test('camera receiver starts, responds to owner and stops with registration cleanup',async()=>{
 const net=require('node:net');const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
 const previous=process.env.AUDIO_MEMORY_TEST_CAMERA_PORT;process.env.AUDIO_MEMORY_TEST_CAMERA_PORT=String(port);
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-visual-worker-'));
 const controller=createServiceController({root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'registry'),kind:'camera'});
 try {
  await fs.writeFile(path.join(root,'classroom-mode.json'),JSON.stringify({enabled:true}));
  const started=await controller.start();assert.equal(started.status,'owned',started.message);
  const runtime=JSON.parse(await fs.readFile(path.join(root,'out','scene','runtime.json'),'utf8'));
  const response=await fetch('http://127.0.0.1:'+port+'/status',{headers:{Authorization:'Bearer '+runtime.token}});
  assert.equal(response.status,200);assert.equal((await response.json()).recording,false);
  assert.equal((await controller.stop()).status,'stopped');
  await assert.rejects(fs.access(path.join(root,'out','scene','runtime.json')));
  const records=JSON.parse(await fs.readFile(path.join(root,'registry','process-registry.json'),'utf8')).processes;
  assert.ok(records.length===1 && records.every(x=>x.status==='exited'));
 } finally { if(controller.isOwned())await controller.stop();await removeFixture(root);if(previous===undefined)delete process.env.AUDIO_MEMORY_TEST_CAMERA_PORT;else process.env.AUDIO_MEMORY_TEST_CAMERA_PORT=previous; }
});
