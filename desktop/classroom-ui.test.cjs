const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');const {spawn}=require('node:child_process');const {removeFixture}=require('./test-fixtures.cjs');
(async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-ui-'));
try {
 const program=path.join(root,'program'),appdata=path.join(root,'appdata');await fs.mkdir(program);await fs.mkdir(appdata);
 const project=path.resolve(__dirname,'..');for(const name of await fs.readdir(project)){if(name.endsWith('.py')&&!name.startsWith('test_'))await fs.copyFile(path.join(project,name),path.join(program,name));}
 const stub=`import sys,time,wave\nfrom pathlib import Path\nif '--once' not in sys.argv:\n if '--ready-file' in sys.argv:Path(sys.argv[sys.argv.index('--ready-file')+1]).write_text('ready')\n p=Path(sys.argv[sys.argv.index('--stop-file')+1])\n while not p.exists():time.sleep(.05)\n if '--out' in sys.argv:\n  out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir(parents=True,exist_ok=True)\n  if out.name=='record':\n   with wave.open(str(out/'fixture.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(320))\n`;
 for(const name of ['recorder.py','transcriber.py','material_bridge.py'])await fs.writeFile(path.join(program,name),stub);
 const env={...process.env,AUDIO_MEMORY_TEST_USER_DATA:appdata,AUDIO_MEMORY_TEST_REGISTRY:path.join(__dirname,'registry.mjs'),AUDIO_MEMORY_TEST_PROJECT_ROOT:program,AUDIO_MEMORY_TEST_PYTHON:path.join(project,'.venv','Scripts','python.exe'),AUDIO_MEMORY_ROOT:root,AUDIO_MEMORY_DESKTOP_CLASSROOM_TEST:'1'};delete env.ELECTRON_RUN_AS_NODE;
 const child=spawn(path.join(__dirname,'node_modules','electron','dist','electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'inherit'});
 const timer=setTimeout(()=>child.kill(),70000);const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve)});clearTimeout(timer);if(code!==0)throw new Error('Classroom UI exit '+code);
 const records=JSON.parse(await fs.readFile(path.join(appdata,'process-registry','process-registry.json'),'utf8')).processes;
 if(records.length!==8||records.some(x=>x.status!=='exited'))throw new Error('Classroom processes not unregistered: '+records.length);
 const state=JSON.parse(await fs.readFile(path.join(root,'classroom-mode.json'),'utf8'));if(state.enabled)throw new Error('Classroom mode not disabled');
 if(!(await fs.stat(path.join(root,'record','fixture.wav'))).size)throw new Error('Fixture audio missing');
 console.log('PASS: classroom UI starts/stops isolated services and saves synthetic audio');
}finally{await removeFixture(root)}})().catch(error=>{console.error(error.message);process.exitCode=1});
