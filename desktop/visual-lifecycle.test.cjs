const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {removeFixture} = require('./test-fixtures.cjs');
(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'audio-visual-worker-'));
  try {
    const appdata = path.join(root,'appdata'); await fs.mkdir(appdata);
    const env={...process.env,AUDIO_MEMORY_TEST_USER_DATA:appdata,AUDIO_MEMORY_TEST_REGISTRY:path.join(__dirname,'registry.mjs'),AUDIO_MEMORY_TEST_PROJECT_ROOT:path.resolve(__dirname,'..'),AUDIO_MEMORY_TEST_PYTHON:path.resolve(__dirname,'..','.venv','Scripts','python.exe'),AUDIO_MEMORY_ROOT:root,AUDIO_MEMORY_DESKTOP_VISUAL_TEST:'1'};
    delete env.ELECTRON_RUN_AS_NODE;
    const child=spawn(path.join(__dirname,'node_modules','electron','dist','electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'inherit'});
    const timer=setTimeout(()=>child.kill(),35000);
    const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve)});clearTimeout(timer);
    if(code!==0)throw new Error('Visual UI lifecycle exit '+code);
    const records=JSON.parse(await fs.readFile(path.join(appdata,'process-registry','process-registry.json'),'utf8')).processes;
    if(records.length!==2 || records.some(x=>x.status!=='exited'))throw new Error('Visual worker not unregistered');
    console.log('PASS: visual UI starts and stops isolated worker');
  } finally { await removeFixture(root); }
})().catch(error=>{console.error(error.message);process.exitCode=1});
