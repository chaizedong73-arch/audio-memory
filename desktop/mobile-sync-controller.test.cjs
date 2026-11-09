const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const os=require('node:os');const https=require('node:https');const {createServiceController}=require('./service-controller.cjs');const {removeFixture}=require('./test-fixtures.cjs');
test('phone receiver starts registered HTTPS process, validates token, and stops cleanly',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-controller-'));
 const controller=createServiceController({root,projectRoot:path.resolve(__dirname,'..'),nodeExecutable:process.execPath,pythonExecutable:path.resolve(__dirname,'..','.venv/Scripts/python.exe'),registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'registry'),kind:'mobile-sync'});
 try{const started=await controller.start();assert.equal(started.status,'owned',started.message);
 const state=JSON.parse(await fs.readFile(path.join(root,'out/mobile-sync-status.json'),'utf8'));assert.equal(state.status,'ready');
 const token=await fs.readFile(path.join(root,'config/mobile-sync/access-token'),'utf8');
 const request=auth=>new Promise((resolve,reject)=>{const r=https.get('https://127.0.0.1:8769/v1/sync/health',{rejectUnauthorized:false,headers:{Authorization:'Bearer '+auth}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});r.on('error',reject);});
 assert.equal(await request(token),200);assert.equal(await request('wrong-token'),401);
 assert.equal((await controller.stop()).status,'stopped');assert.equal(controller.isOwned(),false);
 assert.equal(JSON.parse(await fs.readFile(path.join(root,'out/mobile-sync-status.json'),'utf8')).status,'stopped');
 const records=JSON.parse(await fs.readFile(path.join(root,'registry/process-registry.json'),'utf8')).processes;assert.ok(records.every(p=>p.status!=='running'));
 }finally{if(controller.isOwned())await controller.stop();await removeFixture(root);}
});
