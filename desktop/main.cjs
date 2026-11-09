const { app, BrowserWindow, ipcMain, shell, dialog, safeStorage } = require('electron');
const path = require('node:path');
const { readTranscripts, refreshTranscripts, readContext, correctTranscript, readVisual } = require('./gateway-client.cjs');
const { importVideo } = require('./video-import.cjs');
const { createClassroomFlow } = require('./classroom-flow.cjs');
const cameraClient = require('./camera-client.cjs');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { createServiceController } = require('./service-controller.cjs');
const fs = require('node:fs');
const os = require('node:os');
if (process.env.AUDIO_MEMORY_TEST_USER_DATA) app.setPath('userData', process.env.AUDIO_MEMORY_TEST_USER_DATA);
const root = process.env.AUDIO_MEMORY_ROOT || (app.isPackaged ? path.join(app.getPath('userData'),'data') : path.resolve(__dirname, '..', '..', '数据'));
let controller;
let contextController;
let recordingController;
let visualController;
let cameraController;
let mobileSyncController;
let classroomFlow;
let transcriptionMode='local';
let asrProvider=null;
let providerLoadError=false;
let quitting = false;
let closing = false;
app.whenReady().then(() => {
  const globalRegistry = path.join(os.homedir(), '.tools', 'ai-agent-monitor', 'registry.mjs');
  const registryPath = process.env.AUDIO_MEMORY_TEST_REGISTRY || (fs.existsSync(globalRegistry) ? globalRegistry : app.isPackaged ? path.join(process.resourcesPath,'backend','registry.mjs') : path.join(__dirname, 'registry.mjs'));
  const registryDir = path.join(app.getPath('userData'),'process-registry');
  const registryStore = registryPath === globalRegistry ? path.join(path.dirname(globalRegistry),'data') : registryDir;
  const options = { root, projectRoot:process.env.AUDIO_MEMORY_TEST_PROJECT_ROOT || (app.isPackaged ? path.join(process.resourcesPath,'backend') : path.resolve(__dirname, '..')), pythonExecutable:process.env.AUDIO_MEMORY_TEST_PYTHON || undefined, nodeExecutable:process.execPath, registryPath, registryDir, registryStore };
  controller = createServiceController(options);
  contextController = createServiceController({...options,kind:'context'});
  const cloudConfig=process.env.AUDIO_MEMORY_TEST_CLOUD_CONFIG || path.join(root,'config','ark_config.json');
  const modeFile=path.join(app.getPath('userData'),'transcription-mode.json');
  try {const saved=JSON.parse(fs.readFileSync(modeFile,'utf8'));if(['local','cloud','legacy'].includes(saved.mode))transcriptionMode=saved.mode;}catch{}
  const providerFile=path.join(app.getPath('userData'),'asr-provider.encrypted');
  try {if(fs.existsSync(providerFile)){if(!safeStorage.isEncryptionAvailable())throw new Error('encryption unavailable');asrProvider=JSON.parse(safeStorage.decryptString(fs.readFileSync(providerFile)));}}catch{providerLoadError=true;}
  recordingController = createServiceController({...options,kind:'recording',transcriptionSettings:()=>({mode:transcriptionMode==='local'?'local':'cloud',config:cloudConfig,provider:transcriptionMode==='legacy'?null:asrProvider})});
  mobileSyncController=createServiceController({...options,kind:'mobile-sync'});
  visualController = createServiceController({...options,kind:'visual'});
  cameraController = createServiceController({...options,kind:'camera'});
  const setClassroom = async enabled => {
    const python=options.pythonExecutable || [path.join(options.projectRoot,'runtime','python.exe'),path.join(options.projectRoot,'.venv','Scripts','python.exe')].find(p=>fs.existsSync(p));
    if (!python) throw new Error('未找到程序运行环境');
    await promisify(execFile)(python,['-c','import classroom_mode,sys; classroom_mode.set_enabled(sys.argv[1],sys.argv[2]=="1")',root,enabled?'1':'0'],{cwd:options.projectRoot,windowsHide:true,timeout:10000});
  };
  const readClassroomMode=async()=>{
    try {return JSON.parse(await fs.promises.readFile(path.join(root,'classroom-mode.json'),'utf8')).enabled===true;}
    catch(error){if(error.code==='ENOENT')return false;throw error;}
  };
  classroomFlow=createClassroomFlow({services:{gateway:controller,visual:visualController,context:contextController,camera:cameraController,recording:recordingController},setMode:setClassroom,readMode:readClassroomMode});
  const cameraStatus = async () => {
    if (!cameraController.isOwned()) return {status:'offline'};
    const result=await cameraClient.request(root,'/status');
    if(result.status!=='ready') return result;
    const data=result.data;
    const readImage=async filename=>{try {const file=path.join(root,'out','scene',filename);return 'data:image/png;base64,'+(await fs.promises.readFile(file)).toString('base64');}catch{return ''}};
    let latestPage='',ocrText='',ocrState='暂无页面';
    try {
      const folder=await fs.promises.realpath(path.join(root,'out','scene','ppt'));
      const source=await fs.promises.realpath(String(data.ppt?.latest || ''));
      if(!source.startsWith(folder+path.sep))throw new Error('invalid page');
      latestPage='data:image/png;base64,'+(await fs.promises.readFile(source)).toString('base64');ocrState='等待识别';
      const catalog=JSON.parse(await fs.promises.readFile(path.join(root,'out','ppt-concepts','catalog.json'),'utf8'));
      const entry=catalog.pages[source];
      if(entry && /^[a-f0-9]{64}$/i.test(entry.hash)) {const result=JSON.parse(await fs.promises.readFile(path.join(root,'out','ppt-concepts',entry.hash+'.json'),'utf8'));ocrText=typeof result.text==='string'?result.text:'';ocrState=ocrText?'已识别':'未识别到文字';}
    } catch {}
    return {status:'ready',connected:!!data.connected,recording:!!data.recording,phone:data.phone,error:data.error,ppt:data.ppt,
      preview:await readImage('preview.png'),latestPage,ocrText,ocrState,remote:data.remote ? {status:data.remote.status,message:data.remote.message,url:data.remote.url,captureQr:data.remote.status==='ready' ? await readImage('remote/capture-qr.png') : ''} : null,wifi:data.wifi ? {ip:data.wifi.ip,fingerprint:data.wifi.fingerprint,certificateQr:await readImage('wifi/certificate-qr.png'),captureQr:await readImage('wifi/capture-qr.png')} : null};
  };
  const cameraHeartbeat=setInterval(()=>{if(cameraController.isOwned())void cameraClient.request(root,'/status');},5000);
  app.once('will-quit',()=>clearInterval(cameraHeartbeat));
  ipcMain.handle('transcripts:read', (_event, options) => readTranscripts(root, fetch, options));
  ipcMain.handle('transcripts:refresh', () => refreshTranscripts(root));
  ipcMain.handle('transcripts:correct', (_event, value) => correctTranscript(root, value));
  ipcMain.handle('context:read', () => readContext(root));
  ipcMain.handle('visual:read', () => readVisual(root));
  ipcMain.handle('visual:start', () => visualController.start());
  ipcMain.handle('visual:stop', () => visualController.stop());
  ipcMain.handle('visual:status', () => visualController.isOwned());
  ipcMain.handle('camera:start', async () => {
    try { const alreadyEnabled=await readClassroomMode();if(!alreadyEnabled)await setClassroom(true); const result=await cameraController.start(); if(result.status==='error'&&!alreadyEnabled)await setClassroom(false); return result; }
    catch { return {status:'error',message:'无法启动课堂采集，请查看日志'}; }
  });
  ipcMain.handle('camera:status', () => cameraStatus());
  ipcMain.handle('camera:wifi', () => cameraClient.request(root,'/wifi',{}));
  ipcMain.handle('camera:remote', () => cameraClient.request(root,'/remote',{}));
  ipcMain.handle('camera:remote-stop', () => cameraClient.request(root,'/remote/stop',{}));
  ipcMain.handle('camera:usb', async () => {
    if (!cameraController.isOwned()) return {status:'error',message:'请先启动手机采集'};
    const python=options.pythonExecutable || [path.join(options.projectRoot,'runtime','python.exe'),path.join(options.projectRoot,'.venv','Scripts','python.exe')].find(p=>fs.existsSync(p));
    if(!python)return {status:'error',message:'未找到程序运行环境'};
    try {
      const result=await promisify(execFile)(python,[path.join(options.projectRoot,'scene_usb.py'),'--root',root],{cwd:options.projectRoot,windowsHide:true,timeout:45000,env:{...process.env,PYTHONUTF8:'1',AUDIO_MEMORY_REGISTRY_PATH:registryPath,AUDIO_MEMORY_REGISTRY_EXECUTABLE:process.execPath,AUDIO_MEMORY_PROCESS_REGISTRY_DIR:registryDir}});
      return {status:'ready',message:result.stdout.trim()};
    } catch(error) {return {status:'error',message:String(error.stdout || 'USB 连接失败，请检查手机和日志').trim().slice(0,500)};}
  });
  ipcMain.handle('camera:command', (_event,name) => ['record','preview','snapshot'].includes(name) ? cameraClient.request(root,'/command',{name}) : {status:'error',message:'无效操作'});
  ipcMain.handle('camera:stop', async () => { const result=await cameraController.stop(); if(result.status==='stopped' && !classroomFlow.isActive())await setClassroom(false); return result; });
  ipcMain.handle('classroom:start', () => classroomFlow.start());
  ipcMain.handle('classroom:stop', () => classroomFlow.stop());
  ipcMain.handle('classroom:status', () => ({active:classroomFlow.isActive(),recording:{owned:recordingController.isOwned(),ready:recordingController.isReady()},context:contextController.isOwned(),camera:cameraController.isOwned(),visual:visualController.isOwned(),gateway:controller.isOwned()}));
  ipcMain.handle('visual:import', async () => {
    const choice = await dialog.showOpenDialog({properties:['openFile'],filters:[{name:'录像',extensions:['mp4','webm','mov','mkv']}]});
    if (choice.canceled || !choice.filePaths.length) return {status:'cancelled'};
    try { return await importVideo(root, choice.filePaths[0]); }
    catch { return {status:'error',message:'导入失败，请检查文件和存储空间；原文件未改动。'}; }
  });
  ipcMain.handle('gateway:start', () => controller.start());
  ipcMain.handle('gateway:stop', () => controller.stop());
  ipcMain.handle('context:start', () => contextController.start());
  ipcMain.handle('context:stop', () => contextController.stop());
  ipcMain.handle('context:status', () => contextController.isOwned());
  ipcMain.handle('recording:start', () => recordingController.start());
  const switchMode=require('./transcription-mode.cjs').createModeSwitcher({
    controller:recordingController,getMode:()=>transcriptionMode,setMode:mode=>{transcriptionMode=mode;},
    validate:mode=>!['local','cloud','legacy'].includes(mode)?'无效模式':
      mode==='cloud'&&providerLoadError?'保存的云端配置暂时无法读取，请重新保存配置':
      mode==='cloud'&&!asrProvider?'请先配置云端转写服务':
      mode==='legacy'&&!fs.existsSync(cloudConfig)?'本机火山方舟配置不可用':'',
    persist:mode=>{const temp=modeFile+'.tmp';fs.writeFileSync(temp,JSON.stringify({mode}));fs.renameSync(temp,modeFile);}
  });
  ipcMain.handle('transcription:mode',(_event,mode)=>switchMode(mode));
  ipcMain.handle('mobile-sync:start',()=>mobileSyncController.start());
  ipcMain.handle('mobile-sync:remote',(_event,stop)=>{if(!mobileSyncController.isOwned())return {status:'error',message:'请先开启手机同步接收。'};return require('./mobile-sync-client.cjs').remoteCommand(root,stop===true);});
  ipcMain.handle('mobile-sync:stop',()=>mobileSyncController.stop());
  ipcMain.handle('mobile-sync:status',async()=>{if(!mobileSyncController.isOwned())return {status:'stopped',pairings:[]};try{return JSON.parse(await fs.promises.readFile(path.join(root,'out/mobile-sync-status.json'),'utf8'));}catch{return {status:'starting',pairings:[]};}});
  ipcMain.handle('mobile-sync:copy',async(_event,code)=>{try{const status=JSON.parse(await fs.promises.readFile(path.join(root,'out/mobile-sync-status.json'),'utf8'));if(!mobileSyncController.isOwned()||!(status.pairings.some(p=>p.code===code)||(status.remote?.status==='ready'&&status.remote.code===code)))return false;require('electron').clipboard.writeText(code);return true;}catch{return false;}});
  ipcMain.handle('usage:read',()=>require('./usage-ledger.cjs').readUsage(root));
  ipcMain.handle('transcription:provider-read',()=>asrProvider ? {mode:transcriptionMode,configured:true,url:asrProvider.url,model:asrProvider.model,protocol:asrProvider.protocol,legacyAvailable:fs.existsSync(cloudConfig)} : {mode:transcriptionMode,configured:false,legacyAvailable:fs.existsSync(cloudConfig),message:providerLoadError?'保存的云端配置无法读取，请重新保存配置。':''});
  ipcMain.handle('transcription:provider-save',(_event,value)=>{
    if(recordingController.isOwned())return {status:'error',message:'请先停止录音'};
    try {
      if(!value || !['ark_audio','openai_transcription'].includes(value.protocol) || typeof value.model!=='string' || !/^[a-zA-Z0-9._:-]{1,150}$/.test(value.model) || typeof value.key!=='string' || value.key.length>4096)throw new Error('配置内容无效');
      const key=value.key || asrProvider?.key;if(!key)throw new Error('请填写 API 密钥');
      const url=new URL(value.url);if(url.protocol!=='https:' || url.username || url.password || url.search || url.hash)throw new Error('接口地址必须使用 HTTPS');
      if(!safeStorage.isEncryptionAvailable())throw new Error('系统加密不可用');
      let base=url.toString().replace(/\/$/,'');
      for(const suffix of ['/chat/completions','/audio/transcriptions'])if(base.endsWith(suffix))base=base.slice(0,-suffix.length);
      const model=value.protocol==='ark_audio' && value.model.toLowerCase()==='doubao-seed-2.0-mini' ? 'doubao-seed-2-0-mini-260428' : value.model;
      const provider={url:base,model,key,protocol:value.protocol};
      const encrypted=safeStorage.encryptString(JSON.stringify(provider));fs.mkdirSync(path.dirname(providerFile),{recursive:true});
      const temporary=providerFile+'.'+require('node:crypto').randomUUID()+'.tmp';
      try {fs.writeFileSync(temporary,encrypted,{flag:'wx'});fs.renameSync(temporary,providerFile);}finally{try{fs.unlinkSync(temporary)}catch{}}
      asrProvider=provider;providerLoadError=false;return {status:'ready',url:provider.url,model:provider.model};
    }catch(error){return {status:'error',message:error.message || '保存失败'};}
  });
  ipcMain.handle('recording:stop', () => recordingController.stop());
  ipcMain.handle('recording:status', () => ({owned:recordingController.isOwned(),ready:recordingController.isReady()}));
  ipcMain.handle('logs:open', async () => { const logs=path.join(root,'out','ui'); fs.mkdirSync(logs,{recursive:true}); return shell.openPath(logs); });
  const window = new BrowserWindow({ width: 1160, height: 760, minWidth: 820, minHeight: 560, show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false } });
  window.on('close', event => {
    if (!quitting && (controller.isOwned() || contextController.isOwned() || recordingController.isOwned() || visualController.isOwned() || cameraController.isOwned() || mobileSyncController.isOwned())) {
      event.preventDefault();
      if (closing) return;
      closing = true;
      window.webContents.send('services:closing');
      const hadCamera = cameraController.isOwned();
      const hadClassroom=classroomFlow.isActive();
      (async()=>{if(hadClassroom){const result=await classroomFlow.stop();if(result.status!=='stopped')return [result];}return Promise.all([contextController.stop(),recordingController.stop(),visualController.stop(),controller.stop(),cameraController.stop(),mobileSyncController.stop()]);})().then(async results => {
        const failure = results.find(result => result.status !== 'stopped');
        if (failure) { closing=false; require('electron').dialog.showMessageBox(window,{type:'warning',message:failure.message || '功能尚未停止'}); return; }
        if (hadCamera && !hadClassroom) await setClassroom(false);
        quitting=true; app.quit();
      }).catch(() => { closing=false; require('electron').dialog.showMessageBox(window,{type:'warning',message:'无法停止功能，请查看日志。'}); });
    }
  });
  if(process.env.AUDIO_MEMORY_VERIFY_OUTPUT)window.webContents.once('did-finish-load',()=>require(process.env.AUDIO_MEMORY_VERIFY_MOBILE==='1'?'./mobile-sync-ui-verify.cjs':process.env.AUDIO_MEMORY_VERIFY_USAGE==='1'?'./usage-ui-verify.cjs':'./switch-scroll-verify.cjs')(window,app));
  if(process.env.AUDIO_MEMORY_VERIFY_REMOTE_OUTPUT)window.webContents.once('did-finish-load',()=>require('./remote-ui-verify.cjs')(window,app));
  window.loadFile(path.join(__dirname, 'dist', 'index.html'));
  window.once('ready-to-show', () => window.show());
  if(process.env.AUDIO_MEMORY_DESKTOP_PROVIDER_TEST==='1') {
    window.webContents.once('did-finish-load',async()=>{
      try {
        const result=await window.webContents.executeJavaScript("window.audioMemory.saveAsrProvider({url:'https://example.invalid/v1/audio/transcriptions',model:'fixture-model',key:'fixture-secret',protocol:'openai_transcription'}).then(async saved=>({saved,updated:await window.audioMemory.saveAsrProvider({url:'https://example.invalid/v1/audio/transcriptions',model:'fixture-model',key:'',protocol:'openai_transcription'}),read:await window.audioMemory.readAsrProvider()}))");
        if(result.saved.status!=='ready'||result.updated.status!=='ready'||result.read.url!=='https://example.invalid/v1'||!result.read.configured||result.read.key||result.read.model!=='fixture-model')throw new Error('provider roundtrip failed');
        if(fs.readFileSync(providerFile).includes(Buffer.from('fixture-secret')))throw new Error('credential not encrypted');
        app.quit();
      } catch(error){console.error(error.message);app.exit(11)}
    });
  }
  if(process.env.AUDIO_MEMORY_DESKTOP_PROVIDER_READ_TEST==='1') {
    window.webContents.once('did-finish-load',async()=>{
      try {const result=await window.webContents.executeJavaScript('window.audioMemory.readAsrProvider()');if(!result.configured || result.model!=='fixture-model')throw new Error('saved provider unavailable after restart');app.quit();}
      catch(error){console.error(error.message);app.exit(12)}
    });
  }
  if(process.env.AUDIO_MEMORY_DESKTOP_PROVIDER_PRESENT_TEST==='1') {
    window.webContents.once('did-finish-load',async()=>{
      const result=await window.webContents.executeJavaScript('window.audioMemory.readAsrProvider()');
      console.log('provider_configured='+Boolean(result.configured));app.quit();
    });
  }
  if(process.env.AUDIO_MEMORY_DESKTOP_CLOUD_MODE_TEST==='1') {
    window.webContents.once('did-finish-load',async()=>{
      try {
        const waitFor=async expression=>{for(let i=0;i<100;i++){if(await window.webContents.executeJavaScript(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw new Error('UI timeout: '+expression)};
        await new Promise(resolve=>setTimeout(resolve,500));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('录音')).click()");
        await waitFor("!!document.querySelector('select[aria-label=\"音频转写方式\"]')");
        await waitFor("[...document.querySelector('select[aria-label=\"音频转写方式\"]').options].some(x=>x.value==='legacy')");
        await window.webContents.executeJavaScript("const el=document.querySelector('select[aria-label=\"音频转写方式\"]');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,'legacy');el.dispatchEvent(new Event('change',{bubbles:true}));");
        await waitFor("document.body.innerText.includes('已选择云端转写')");app.quit();
      }catch(error){console.error(error.message);app.exit(10)}
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_CLASSROOM_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor=async expression=>{for(let i=0;i<450;i++){if(await window.webContents.executeJavaScript(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw new Error('UI timeout: '+expression)};
        await new Promise(resolve=>setTimeout(resolve,1000));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
        await waitFor("[...document.querySelectorAll('button')].some(x=>x.innerText.includes('开始课堂')&&!x.disabled)");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x=>x.innerText.includes('开始课堂')).click()");
        await waitFor("document.body.innerText.includes('课堂已启动') && [...document.querySelectorAll('button')].some(x=>x.innerText.includes('结束课堂')&&!x.disabled)");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x=>x.innerText.includes('结束课堂')).click()");
        await waitFor("document.body.innerText.includes('课堂已结束') && [...document.querySelectorAll('button')].some(x=>x.innerText.includes('开始课堂')&&!x.disabled)");
        app.quit();
      } catch(error){console.error(error.message);console.error((await window.webContents.executeJavaScript('document.body.innerText')).slice(0,1500));app.exit(9);}
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_CAMERA_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_CAMERA_WIFI_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor=async expression=>{for(let i=0;i<180;i++){if(await window.webContents.executeJavaScript(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw new Error('UI timeout: '+expression)};
        await new Promise(resolve=>setTimeout(resolve,500));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
        await waitFor("[...document.querySelectorAll('.nav-item')].some(x=>x.innerText.includes('PPT采集'))");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('PPT采集')).click()");
        await waitFor("[...document.querySelectorAll('button')].some(x=>x.innerText==='启动手机采集'&&!x.disabled)");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x=>x.innerText==='启动手机采集').click()");
        await waitFor("document.body.innerText.includes('等待手机连接')");
        if(process.env.AUDIO_MEMORY_DESKTOP_CAMERA_WIFI_TEST === '1') {
          await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x=>x.innerText==='Wi-Fi 配对').click()");
          await waitFor("!!document.querySelector('img[alt=\"证书二维码\"]') && !!document.querySelector('img[alt=\"采集二维码\"]')");
          await waitFor("[...document.querySelectorAll('button')].some(x=>x.innerText==='结束采集'&&!x.disabled)");
        }
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x=>x.innerText==='结束采集').click()");
        await waitFor("[...document.querySelectorAll('button')].some(x=>x.innerText==='启动手机采集'&&!x.disabled)");
        app.quit();
      } catch(error){console.error(error.message);app.exit(8);}
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_VISUAL_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor = async expression => { for(let i=0;i<150;i++) { if(await window.webContents.executeJavaScript(expression)) return; await new Promise(resolve => setTimeout(resolve,100)); } throw new Error('UI timeout: '+expression); };
        await new Promise(resolve=>setTimeout(resolve,500));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
        await waitFor("[...document.querySelectorAll('.nav-item')].some(x => x.innerText.includes('PPT采集'))");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
        await new Promise(resolve=>setTimeout(resolve,200));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('PPT采集')).click()");
        await waitFor("[...document.querySelectorAll('button')].some(x => x.innerText === '开始处理' && !x.disabled)");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x => x.innerText === '开始处理').click()");
        await waitFor("document.body.innerText.includes('录像处理运行中')");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('button')].find(x => x.innerText === '停止处理').click()");
        await waitFor("document.body.innerText.includes('录像处理已停止，下次可继续')");
        app.quit();
      } catch (error) { console.error(error.message); app.exit(7); }
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_CORRECTION_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_CORRECTION_STALE_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor = async expression => { for(let i=0;i<150;i++) { if(await window.webContents.executeJavaScript(expression)) return; await new Promise(resolve => setTimeout(resolve,100)); } throw new Error('UI timeout: '+expression); };
        await waitFor("!!document.querySelector('.edit-correction')");
        await window.webContents.executeJavaScript("document.querySelector('.edit-correction').click()");
        await waitFor("!!document.querySelector('textarea')");
        await window.webContents.executeJavaScript("const el=document.querySelector('textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el,'这是视图');el.dispatchEvent(new Event('input',{bubbles:true}));");
        await waitFor("!document.querySelector('.save-correction').disabled");
        if (process.env.AUDIO_MEMORY_DESKTOP_CORRECTION_STALE_TEST === '1') await refreshTranscripts(root);
        await window.webContents.executeJavaScript("document.querySelector('.save-correction').click()");
        if (process.env.AUDIO_MEMORY_DESKTOP_CORRECTION_STALE_TEST === '1') {
          await waitFor("document.body.innerText.includes('取消编辑后刷新核对') && document.querySelector('textarea')?.value === '这是视图'");
        } else {
          await waitFor("document.body.innerText.includes('修订已保存') && document.body.innerText.includes('这是视图')");
        }
        app.quit();
      } catch (error) { console.error(error.message); app.exit(6); }
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_RECORDING_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_RECORDING_CLOSE_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor = async expression => { for(let i=0;i<200;i++) { if(await window.webContents.executeJavaScript(expression)) return; await new Promise(resolve => setTimeout(resolve,100)); } throw new Error('UI timeout: '+expression); };
        await waitFor("[...document.querySelectorAll('.nav-item')].some(x => x.innerText.includes('录音'))");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('录音')).click()");
        await waitFor("!!document.querySelector('.record-start:not(:disabled)')");
        await window.webContents.executeJavaScript("document.querySelector('.record-start').click()");
        await waitFor("!!document.querySelector('.record-stop') && document.body.innerText.includes('正在接收音频')");
        if (process.env.AUDIO_MEMORY_DESKTOP_RECORDING_CLOSE_TEST !== '1') {
          await window.webContents.executeJavaScript("document.querySelector('.record-stop').click()");
          await waitFor("!!document.querySelector('.record-start') && document.body.innerText.includes('录音已保存并停止')");
        }
        app.quit();
      } catch (error) { console.error(error.message); app.exit(5); }
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_CONTEXT_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_CONTEXT_CLOSE_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_CONTEXT_GATEWAY_STOP_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor = async (expression) => { for (let i=0;i<150;i++) { if(await window.webContents.executeJavaScript(expression)) return; await new Promise(resolve => setTimeout(resolve,100)); } throw new Error('UI timeout: '+expression); };
        await waitFor("!!document.querySelector('.primary')");
        await window.webContents.executeJavaScript("document.querySelector('.primary').click()");
        await waitFor("document.body.innerText.includes('材料网关已连接')");
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('情景')).click()");
        await waitFor("!!document.querySelector('.context-start')");
        await window.webContents.executeJavaScript("document.querySelector('.context-start').click()");
        await waitFor("!!document.querySelector('.context-stop')");
        if (process.env.AUDIO_MEMORY_DESKTOP_CONTEXT_GATEWAY_STOP_TEST === '1') {
          await window.webContents.executeJavaScript("document.querySelector('.stop-link').click()");
          await waitFor("document.body.innerText.includes('材料网关未连接') && !!document.querySelector('.context-stop')");
          await window.webContents.executeJavaScript("document.querySelector('.context-stop').click()");
          await waitFor("!document.querySelector('.context-stop')");
        } else if (process.env.AUDIO_MEMORY_DESKTOP_CONTEXT_CLOSE_TEST !== '1') {
          await window.webContents.executeJavaScript("document.querySelector('.context-stop').click()");
          await waitFor("!!document.querySelector('.context-start') && document.body.innerText.includes('自动情景已停止')");
        }
        app.quit();
      } catch (error) { console.error(error.message); app.exit(4); }
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_AUTOSTART_TEST === '1' || process.env.AUDIO_MEMORY_DESKTOP_AUTOCLOSE_TEST === '1') {
    window.webContents.once('did-finish-load', async () => {
      try {
        const waitFor = async (expression) => {
          for (let i=0;i<120;i++) {
            if (await window.webContents.executeJavaScript(expression)) return;
            await new Promise(resolve => setTimeout(resolve,100));
          }
          throw new Error('Timed out waiting for UI state');
        };
        await waitFor("document.body.innerText.includes('资料已连接')");
        app.quit();
      } catch { app.exit(3); }
    });
  }
  if (process.env.AUDIO_MEMORY_DESKTOP_SCREENSHOT) {
    window.webContents.once('did-finish-load', async () => {
      await new Promise(resolve => setTimeout(resolve, 800));
      if (process.env.AUDIO_MEMORY_DESKTOP_OPEN_CONTEXT === '1') {
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('情景')).click()");
      }
      if (process.env.AUDIO_MEMORY_DESKTOP_OPEN_RECORDING === '1') {
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('录音')).click()");
      }
      if (process.env.AUDIO_MEMORY_DESKTOP_OPEN_PROVIDER === '1') {
        for(let i=0;i<80;i++){if(await window.webContents.executeJavaScript("!!document.querySelector('.provider-details')"))break;await new Promise(resolve=>setTimeout(resolve,100));}
        await new Promise(resolve=>setTimeout(resolve,500));
        await window.webContents.executeJavaScript("document.querySelector('.provider-details').open=true");
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      if (process.env.AUDIO_MEMORY_DESKTOP_OPEN_VISUAL === '1') {
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
        await new Promise(resolve=>setTimeout(resolve,200));
        await window.webContents.executeJavaScript("[...document.querySelectorAll('.nav-item')].find(x => x.innerText.includes('PPT采集')).click()");
      }
      if (process.env.AUDIO_MEMORY_DESKTOP_OPEN_EDIT === '1') {
        for (let i=0;i<80;i++) {
          if (await window.webContents.executeJavaScript("!!document.querySelector('.edit-correction')")) break;
          await new Promise(resolve => setTimeout(resolve,100));
        }
        await window.webContents.executeJavaScript("document.querySelector('.edit-correction').click()");
      }
      if (process.env.AUDIO_MEMORY_DESKTOP_EXPECT) {
        let matched = false;
        for (let i=0;i<80;i++) {
          const body = await window.webContents.executeJavaScript('document.body.innerText');
          if (body.includes(process.env.AUDIO_MEMORY_DESKTOP_EXPECT)) { matched = true; break; }
          await new Promise(resolve => setTimeout(resolve,100));
        }
        if (!matched) { app.exit(2); return; }
      }
      const image = await window.webContents.capturePage();
      require('node:fs').writeFileSync(process.env.AUDIO_MEMORY_DESKTOP_SCREENSHOT, image.toPNG());
      app.quit();
    });
  }
});
app.on('window-all-closed', () => app.quit());
