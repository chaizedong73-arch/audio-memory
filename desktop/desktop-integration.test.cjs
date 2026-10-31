const { removeFixture } = require('./test-fixtures.cjs');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');

(async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'audio-desktop-fixture-'));
  const server = http.createServer((req,res) => {
    if (req.headers.authorization !== 'Bearer test-token' || req.url !== '/v1/materials?kind=transcript_segment&limit=100') { res.writeHead(401).end(); return; }
    res.writeHead(200, {'Content-Type':'application/json'}).end(JSON.stringify({total:1,items:[{id:'fixture',source:'out/class/timeline.jsonl',data:{t:'09:32:15',effectiveRecord:{text:'课件内容和字幕按时间关联。'}}}]}));
  });
  try {
    await fs.mkdir(path.join(root,'out','ai-gateway'),{recursive:true});
    await fs.writeFile(path.join(root,'out','ai-gateway','access-token'),'test-token');
    await new Promise((resolve,reject) => { server.once('error',reject); server.listen(8768,'127.0.0.1',resolve); });
    const env = {...process.env,AUDIO_MEMORY_ROOT:root,AUDIO_MEMORY_DESKTOP_EXPECT:'课件内容和字幕按时间关联。',AUDIO_MEMORY_DESKTOP_SCREENSHOT:path.resolve('..','..','audio-memory-build','desktop-connected.png')};
    delete env.ELECTRON_RUN_AS_NODE;
    const child = spawn(path.join(__dirname,'node_modules','electron','dist','electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'inherit'});
    const timer = setTimeout(() => child.kill(),15000);
    const code = await new Promise((resolve,reject) => { child.once('error',reject); child.once('exit',resolve); });
    clearTimeout(timer);
    if(code !== 0) throw new Error('Electron fixture exited '+code);
    if (!(await fs.stat(env.AUDIO_MEMORY_DESKTOP_SCREENSHOT)).size) throw new Error('Screenshot missing');
    console.log('PASS: real Electron window displays transcript from authenticated gateway');
  } finally {
    await new Promise(resolve => server.close(resolve));
    await removeFixture(root);
  }
})().catch(error => { console.error(error.message); process.exitCode=1; });
