const { removeFixture } = require('./test-fixtures.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createServiceController } = require('./service-controller.cjs');
const { readTranscripts } = require('./gateway-client.cjs');
const previousPort=process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT;
test.before(async()=>{const net=require('node:net');const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT=String(server.address().port);await new Promise(resolve=>server.close(resolve));});
test.after(()=>{if(previousPort===undefined)delete process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT;else process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT=previousPort;});

test('starts and registers a gateway, reads it, then stops and unregisters', async () => {
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-controller-'));
 const registryDir=path.join(root,'registry');
 const controller=createServiceController({root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir});
 try {
  const started=await controller.start(); assert.equal(started.status,'owned',started.message); assert.equal(controller.isOwned(),true);
  assert.equal((await readTranscripts(root)).status,'ready');
  const active=JSON.parse(await fs.readFile(path.join(registryDir,'process-registry.json'),'utf8'));
  assert.equal(active.processes.at(-1).status,'running');
  assert.equal((await controller.stop()).status,'stopped'); assert.equal(controller.isOwned(),false);
  const stopped=JSON.parse(await fs.readFile(path.join(registryDir,'process-registry.json'),'utf8'));
  assert.equal(stopped.processes.at(-1).status,'exited');
 } finally { if(controller.isOwned()) await controller.stop(); await removeFixture(root); }
});

test('gateway startup tolerates registry initialization longer than ten seconds', async () => {
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-controller-'));
 const wrapper=path.join(root,'slow-registry.mjs');
 const {pathToFileURL}=require('node:url');
 await fs.writeFile(wrapper,`await new Promise(resolve=>setTimeout(resolve,11000)); await import(${JSON.stringify(pathToFileURL(path.join(__dirname,'registry.mjs')).href)});`);
 const controller=createServiceController({root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:wrapper,registryDir:path.join(root,'registry')});
 try {
  assert.equal((await controller.start()).status,'owned');
  assert.equal((await readTranscripts(root)).status,'ready');
  assert.equal((await controller.stop()).status,'stopped');
 } finally {if(controller.isOwned())await controller.stop();await removeFixture(root);}
});
