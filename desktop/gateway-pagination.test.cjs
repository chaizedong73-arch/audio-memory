const { removeFixture } = require('./test-fixtures.cjs');
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const os=require('node:os');
const {createServiceController}=require('./service-controller.cjs');const {readTranscripts,refreshTranscripts}=require('./gateway-client.cjs');
test('real gateway paginates a snapshot and refreshes appended subtitles',async()=>{
 const net=require('node:net');const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
 const previous=process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT;process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT=String(port);
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-pages-'));const controller=createServiceController({root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'registry')});
 try {const day=path.join(root,'out','20261031');await fs.mkdir(day,{recursive:true});const file=path.join(day,'timeline.jsonl');
 const row=i=>JSON.stringify({t:'09:32:15',text:'字幕'+i,file:'fixture'+i,start:i,end:i+1});await fs.writeFile(file,Array.from({length:101},(_,i)=>row(i)).join('\n')+'\n');
 const started=await controller.start();assert.equal(started.status,'owned',started.message);
 const first=await readTranscripts(root);assert.equal(first.total,101);assert.equal(first.items.length,100);assert.equal(first.nextOffset,100);
 const second=await readTranscripts(root,fetch,{offset:first.nextOffset,snapshot:first.snapshot});assert.equal(second.items.length,1);assert.equal(new Set([...first.items,...second.items].map(item=>item.id)).size,101);assert.ok([...first.items,...second.items].some(item=>item.text==='字幕100'));
 await fs.appendFile(file,row(101)+'\n');const fresh=await refreshTranscripts(root);assert.equal(fresh.total,102);
 assert.equal((await readTranscripts(root,fetch,{offset:100,snapshot:first.snapshot})).status,'stale');
 const next=path.join(root,'out','20261101');await fs.mkdir(next,{recursive:true});await fs.writeFile(path.join(next,'timeline.jsonl'),row(999)+'\n');
 const today=await refreshTranscripts(root,fetch,{day:'2026-11-01'});assert.equal(today.total,1);assert.equal(today.items[0].text,'字幕999');
 const history=await readTranscripts(root,fetch,{day:'2026-10-31'});assert.equal(history.total,102);assert.equal(history.items.length,100);
 const secondHistory=await readTranscripts(root,fetch,{day:'2026-10-31',offset:100,snapshot:history.snapshot});assert.equal(secondHistory.items.length,2);
 const all=await readTranscripts(root);assert.equal(all.total,103);
 }finally{if(controller.isOwned())await controller.stop();await removeFixture(root);if(previous===undefined)delete process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT;else process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT=previous}
});
