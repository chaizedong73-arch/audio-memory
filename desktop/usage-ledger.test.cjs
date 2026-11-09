const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');const {readUsage}=require('./usage-ledger.cjs');const {removeFixture}=require('./test-fixtures.cjs');
test('ledger survives reopen and bad lines, counts unknown separately, and uses Shanghai date',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-ui-'));
 try{const folder=path.join(root,'out','cloud-usage');await fs.mkdir(folder,{recursive:true});
 const rows=[{id:'1',time:'2026-11-06T01:00:00+08:00',date:'2026-11-06',model:'mini',estimatedYuan:.0064},
 {id:'2',time:'2026-11-06T01:00:01+08:00',date:'2026-11-06',model:'custom',estimatedYuan:null}];
 await fs.writeFile(path.join(folder,'2026-11-06.jsonl'),JSON.stringify(rows[0])+'\n{broken\n'+JSON.stringify(rows[1])+'\n');
 await fs.writeFile(path.join(folder,'2026-11-05.jsonl'),JSON.stringify({...rows[0],id:'old',date:'2026-11-05'})+'\n');
 const r=await readUsage(root,new Date('2026-11-05T17:00:00Z'));assert.equal(r.status,'ready');assert.deepEqual(r.today,{calls:2,estimatedYuan:.0064,unknown:1});assert.deepEqual(r.total,{calls:3,estimatedYuan:.0128,unknown:1});assert.equal(r.warnings,1);assert.equal(r.items[0].id,'2');
 assert.deepEqual(await readUsage(root,new Date('2026-11-05T17:00:00Z')),r);
 }finally{await removeFixture(root);}
});
test('empty ledger is ready with no calls',async()=>{const r=await readUsage(path.join(os.tmpdir(),'no-such-audio-cost-fixture'));assert.equal(r.status,'ready');assert.equal(r.total.calls,0);});
test('synced mobile usage is counted once even when its metadata is received again',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-ui-'));
 try{const folder=path.join(root,'out/mobile-sync','a'.repeat(32),'b'.repeat(32));await fs.mkdir(folder,{recursive:true});
 const meta={usage:[{id:'mobile-request',time:'2026-11-06T01:00:00+08:00',date:'2026-11-06',model:'mini',estimatedYuan:.00069},{id:'mobile-unknown',time:'2026-11-06T01:00:01+08:00',date:'2026-11-06',model:'custom',estimatedYuan:null}]};
 for(let i=0;i<2;i++){await fs.writeFile(path.join(folder,'metadata.json'),JSON.stringify(meta));const r=await readUsage(root,new Date('2026-11-06T01:00:00Z'));assert.deepEqual(r.total,{calls:2,estimatedYuan:.00069,unknown:1});assert.equal(r.items.length,2);}
 }finally{await removeFixture(root);}
});
