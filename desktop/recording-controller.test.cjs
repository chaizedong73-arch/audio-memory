const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const path=require('node:path');const os=require('node:os');const {removeFixture}=require('./test-fixtures.cjs');const {createServiceController}=require('./service-controller.cjs');
test('recording supervisor starts registered child units and stops them without a microphone',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-worker-'));const program=path.join(root,'program'),registryDir=path.join(root,'registry');
 await fs.mkdir(program);for(const name of ['run_core.py','data_location.py'])await fs.copyFile(path.resolve(__dirname,'..',name),path.join(program,name));
 const stub=`import sys,time\nfrom pathlib import Path\nif '--once' not in sys.argv:\n if '--ready-file' in sys.argv:Path(sys.argv[sys.argv.index('--ready-file')+1]).write_text('ready')\n p=Path(sys.argv[sys.argv.index('--stop-file')+1])\n while not p.exists():time.sleep(.05)\n`;
 for(const name of ['recorder.py','transcriber.py','material_bridge.py'])await fs.writeFile(path.join(program,name),stub);
 const controller=createServiceController({root,projectRoot:program,nodeExecutable:process.execPath,pythonExecutable:path.resolve(__dirname,'..','.venv','Scripts','python.exe'),registryPath:path.join(__dirname,'registry.mjs'),registryDir,kind:'recording'});
 try {const started=await controller.start();assert.equal(started.status,'owned',started.message);assert.equal(controller.isReady(),true);
  const stopped=await controller.stop();assert.equal(stopped.status,'stopped');assert.equal(controller.isOwned(),false);
  const entries=JSON.parse(await fs.readFile(path.join(registryDir,'process-registry.json'),'utf8')).processes;assert.equal(entries.length,4);assert.ok(entries.every(x=>x.status==='exited'));
 }finally{if(controller.isOwned())await controller.stop();await removeFixture(root)}
});


test('unexpected recorder failure is reported instead of claiming audio was saved',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-worker-'));const program=path.join(root,'program'),registryDir=path.join(root,'registry');
 await fs.mkdir(program);for(const name of ['run_core.py','data_location.py'])await fs.copyFile(path.resolve(__dirname,'..',name),path.join(program,name));
 const failing=`import sys,time\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index('--ready-file')+1]).write_text('ready')\ntime.sleep(.5)\nraise SystemExit(7)\n`;
 const idle=`import sys,time\nfrom pathlib import Path\nif '--once' not in sys.argv:\n p=Path(sys.argv[sys.argv.index('--stop-file')+1])\n while not p.exists():time.sleep(.05)\n`;
 await fs.writeFile(path.join(program,'recorder.py'),failing);for(const name of ['transcriber.py','material_bridge.py'])await fs.writeFile(path.join(program,name),idle);
 const controller=createServiceController({root,projectRoot:program,nodeExecutable:process.execPath,pythonExecutable:path.resolve(__dirname,'..','.venv','Scripts','python.exe'),registryPath:path.join(__dirname,'registry.mjs'),registryDir,kind:'recording'});
 try {assert.equal((await controller.start()).status,'owned');for(let i=0;i<100&&controller.isOwned();i++)await new Promise(r=>setTimeout(r,100));
  assert.equal(controller.isOwned(),false);const result=await controller.stop();assert.equal(result.status,'error');assert.match(result.message,/异常退出/);
 }finally{if(controller.isOwned())await controller.stop();await removeFixture(root)}
});
