const { removeFixture } = require('./test-fixtures.cjs');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { readTranscripts, refreshTranscripts } = require('./gateway-client.cjs');

test('missing gateway credential returns offline without a request', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'audio-gateway-'));
  try { assert.deepEqual(await readTranscripts(root, () => { throw new Error('must not call'); }), { status:'offline', items:[], total:0, snapshot:'', nextOffset:null }); }
  finally { await removeFixture(root); }
});
test('reads transcript and never returns the credential', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'audio-gateway-'));
  try {
    await fs.mkdir(path.join(root,'out','ai-gateway'), { recursive:true });
    await fs.writeFile(path.join(root,'out','ai-gateway','access-token'),'fixture-token');
    const result = await readTranscripts(root, async (url, options) => {
      assert.match(url, /^http:\/\/127\.0\.0\.1:8768\//);
      assert.equal(options.headers.Authorization, 'Bearer fixture-token');
      return { ok:true, json:async () => ({ total:1, items:[{id:'1',data:{effectiveRecord:{text:'测试字幕'},t:'10:20:00'},source:'out/day/timeline.jsonl'}]}) };
    });
    assert.equal(result.items[0].text, '测试字幕');
    assert.equal(result.items[0].time, '10:20:00');
    assert.equal(JSON.stringify(result).includes('fixture-token'), false);
  } finally { await removeFixture(root); }
});
test('gateway errors are presented without exposing response data', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'audio-gateway-'));
  try {
    await fs.mkdir(path.join(root,'out','ai-gateway'), { recursive:true });
    await fs.writeFile(path.join(root,'out','ai-gateway','access-token'),'fixture-token');
    assert.equal((await readTranscripts(root, async () => ({ ok:false }))).status, 'error');
    assert.equal((await readTranscripts(root, async () => { throw new Error('network'); })).status, 'offline');
  } finally { await removeFixture(root); }
});

test('uses snapshot and offset and reports changed snapshot', async () => {
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-gateway-'));
 try { await fs.mkdir(path.join(root,'out','ai-gateway'),{recursive:true});await fs.writeFile(path.join(root,'out','ai-gateway','access-token'),'fixture-token');
 const snapshot='a'.repeat(32);
 const result=await readTranscripts(root, async url=>{assert.match(url,/offset=100/);assert.match(url,/snapshot=a{32}/);return {ok:false,status:409}}, {offset:100,snapshot});
 assert.equal(result.status,'stale');
 } finally {await removeFixture(root);}
});
test('refresh rebuilds gateway snapshot before reading', async () => {
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-gateway-'));
 try { await fs.mkdir(path.join(root,'out','ai-gateway'),{recursive:true});await fs.writeFile(path.join(root,'out','ai-gateway','access-token'),'fixture-token');
 const calls=[];const result=await refreshTranscripts(root,async (url,options)=>{calls.push([url,options.method]);if(url.endsWith('/v1/refresh'))return {ok:true};return {ok:true,json:async()=>({total:0,items:[]})}});
 assert.equal(result.status,'ready');assert.equal(calls[0][1],'POST');assert.match(calls[1][0],/v1\/materials/);
 } finally {await removeFixture(root);}
});
