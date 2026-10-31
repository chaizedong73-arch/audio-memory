const { removeFixture } = require('./test-fixtures.cjs');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
 const root = await fs.mkdtemp(path.join(os.tmpdir(),'audio-real-gateway-'));
 const project = path.resolve(__dirname,'..');
 let gateway;
 try {
  const day = path.join(root,'out','20261031'); await fs.mkdir(day,{recursive:true});
  await fs.writeFile(path.join(day,'timeline.jsonl'), JSON.stringify({t:'09:32:15',ts:1793410335,text:'真实网关连接测试字幕。',file:'fixture',start:0,end:1})+'\n');
  const stop = path.join(root,'stop');
  gateway = spawn(path.join(project,'.venv','Scripts','python.exe'),[path.join(project,'ai_material_gateway.py'),'serve','--root',root,'--port','8768','--stop-file',stop],{cwd:project,windowsHide:true,stdio:'ignore',env:{...process.env,PYTHONUTF8:'1'}});
  let ready=false;
  for(let i=0;i<100;i++) {
   if(gateway.exitCode!==null) throw new Error('Fixture gateway exited early');
   try { const token=(await fs.readFile(path.join(root,'out','ai-gateway','access-token'),'utf8')).trim();
    const r=await fetch('http://127.0.0.1:8768/v1/health',{headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(500)});
    if(r.ok){ready=true;break;}
   } catch {} await sleep(100);
  }
  if(!ready) throw new Error('Fixture gateway not ready');
  const env={...process.env,AUDIO_MEMORY_ROOT:root,AUDIO_MEMORY_DESKTOP_EXPECT:'真实网关连接测试字幕。',AUDIO_MEMORY_DESKTOP_SCREENSHOT:path.resolve('..','..','audio-memory-build','desktop-real-gateway.png')}; delete env.ELECTRON_RUN_AS_NODE;
  const child=spawn(path.join(__dirname,'node_modules','electron','dist','electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'inherit'});
  const timer=setTimeout(()=>child.kill(),15000);
  const result=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);}); clearTimeout(timer);
  if(result!==0) throw new Error('Electron exited '+result);
  console.log('PASS: Electron reads fixture transcript from actual Python gateway');
 } finally {
  if(gateway && gateway.exitCode===null){ await fs.writeFile(path.join(root,'stop'),'stop');
   await Promise.race([new Promise(resolve=>gateway.once('exit',resolve)),sleep(5000)]);
   if(gateway.exitCode===null){gateway.kill();await new Promise(resolve=>gateway.once('exit',resolve));}
  }
  await removeFixture(root);
 }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
