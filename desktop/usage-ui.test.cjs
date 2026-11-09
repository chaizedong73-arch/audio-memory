const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');const {spawn}=require('node:child_process');const {removeFixture}=require('./test-fixtures.cjs');
(async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'audio-recording-ui-'));
 try{
  const output=path.resolve(__dirname,'..','test-artifacts','2026-11-06-costs');
  const env={...process.env,AUDIO_MEMORY_ROOT:root,AUDIO_MEMORY_TEST_USER_DATA:path.join(root,'appdata'),AUDIO_MEMORY_TEST_REGISTRY:path.join(__dirname,'registry.mjs'),AUDIO_MEMORY_TEST_PROJECT_ROOT:path.join(root,'unused'),AUDIO_MEMORY_VERIFY_OUTPUT:output,AUDIO_MEMORY_VERIFY_USAGE:'1',AUDIO_MEMORY_VERIFY_USAGE_EMPTY:'1'};delete env.ELECTRON_RUN_AS_NODE;
  const launch=async()=>{const child=spawn(path.join(__dirname,'node_modules','electron','dist','electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'inherit'});const timer=setTimeout(()=>child.kill(),25000);const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve)});clearTimeout(timer);if(code!==0)throw Error('Usage UI exit '+code);};
  await launch();
  const folder=path.join(root,'out','cloud-usage');await fs.mkdir(folder,{recursive:true});
  const row={id:'fixture-real-usage',time:'2026-11-06T00:15:59+08:00',date:'2026-11-06',file:'synthetic-speech.wav',model:'doubao-seed-2-0-mini-260428',audioSeconds:6.383,inputTokens:107,outputTokens:12,estimatedYuan:.00069,status:'response'};
  await fs.writeFile(path.join(folder,'2026-11-06.jsonl'),[row,{...row,id:'fixture-unknown',file:'模拟失败请求.wav',model:'custom-price-unknown',estimatedYuan:null,inputTokens:null,outputTokens:null,status:'error'}].map(x=>JSON.stringify(x)).join('\n')+'\n');
  env.AUDIO_MEMORY_VERIFY_USAGE_EMPTY='0';await launch();await launch();
  console.log('PASS usage controls, empty state, unknown amount, and reopen');
 }finally{await removeFixture(root);}
})().catch(e=>{console.error(e);process.exitCode=1});
