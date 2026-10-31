const { removeFixture } = require('./test-fixtures.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createServiceController } = require('./service-controller.cjs');
const { readTranscripts } = require('./gateway-client.cjs');

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
