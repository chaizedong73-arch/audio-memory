const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { readTranscripts } = require('./gateway-client.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function removeStopDirectory(dir) {
  const real = fs.realpathSync(dir), temp = fs.realpathSync(os.tmpdir());
  if (path.dirname(real).toLowerCase() !== temp.toLowerCase() || !/^audio-memory-(gateway|context|recording|visual|camera)-/.test(path.basename(real))) throw new Error('Invalid temporary directory');
  fs.rmSync(real,{recursive:true,force:true});
}

function createServiceController({root, projectRoot, nodeExecutable, registryPath, registryDir, registryStore = registryDir, kind = 'gateway', pythonExecutable, transcriptionSettings = () => ({mode:'local'})}) {
  if (!['gateway','context','recording','visual','camera'].includes(kind)) throw new Error('Unknown service');
  let processHandle = null;
  let stopDirectory = null;
  let starting = false;
  const alive = () => !!processHandle && processHandle.exitCode === null && processHandle.signalCode === null;
  const clear = () => { processHandle = null; if (stopDirectory) { try { removeStopDirectory(stopDirectory); } catch {} stopDirectory = null; } };
  const completed = () => {
    const failed = processHandle && (processHandle.exitCode !== 0 || processHandle.signalCode !== null);
    clear();
    return failed ? {status:'error',message:kind === 'recording' ? '录音进程异常退出，请检查录音文件和日志' : '进程异常退出，请查看日志'} : {status:'stopped'};
  };
  async function start() {
    if (starting) return { status:'starting' };
    if (alive()) return { status:'owned' };
    if (processHandle) clear();
    if (kind === 'gateway' && (await readTranscripts(root)).status === 'ready') return { status:'external' };
    starting = true;
    try {
      const candidates = pythonExecutable ? [pythonExecutable] : [path.join(projectRoot,'runtime','python.exe'),path.join(projectRoot,'.venv','Scripts','python.exe')];
      const python = candidates.find(candidate => fs.existsSync(candidate));
      if (!python) return { status:'error', message:'未找到程序运行环境' };
      if (!fs.existsSync(registryPath)) return { status:'error', message:'未找到进程管理组件' };
      stopDirectory = fs.mkdtempSync(path.join(os.tmpdir(),`audio-memory-${kind}-`));
      const stopFile = path.join(stopDirectory,'stop');
      const logs = path.join(root,'out','ui'); fs.mkdirSync(logs,{recursive:true});
      const log = fs.openSync(path.join(logs,kind+'.log'),'a');
      const name = 'Audio-Memory-' + kind + '-' + crypto.randomUUID();
      const command = kind === 'gateway' ? [path.join(projectRoot,'ai_material_gateway.py'),'serve','--root',root,'--port','8768','--stop-file',stopFile] : kind === 'context' ? [path.join(projectRoot,'context_auto.py'),'--root',root,'--stop-file',stopFile,'--ready-file',path.join(stopDirectory,'ready')] : kind === 'visual' ? [path.join(projectRoot,'visual_worker.py'),'--root',root,'--watch','--stop-file',stopFile,'--ready-file',path.join(stopDirectory,'ready')] : kind === 'camera' ? [path.join(projectRoot,'scene_capture.py'),'--root',root,'--stop-file',stopFile,'--ready-file',path.join(stopDirectory,'ready')] : [path.join(projectRoot,'run_core.py'),'--root',root,'--stop-file',stopFile,'--ready-file',path.join(stopDirectory,'ready'),'--registry',registryPath,'--registry-executable',nodeExecutable,'--parent-registered-file',path.join(stopDirectory,'parent-registered')];
      let cloudEnv={};
      if(kind==='recording') {
        const settings=transcriptionSettings();
        if(settings.mode==='cloud') {
          if(settings.provider) {
            cloudEnv={AUDIO_MEMORY_ASR_URL:settings.provider.url,AUDIO_MEMORY_ASR_KEY:settings.provider.key,AUDIO_MEMORY_ASR_MODEL:settings.provider.model,AUDIO_MEMORY_ASR_PROTOCOL:settings.provider.protocol};
            command.push('--mode','cloud','--cloud-config',path.join(root,'unused-cloud-config'));
          } else {
            if(!settings.config || !fs.existsSync(settings.config)) {fs.closeSync(log);clear();return {status:'error',message:'请先配置云端转写服务'};}
            command.push('--mode','cloud','--cloud-config',settings.config);
          }
        }
      }
      try {
        processHandle = spawn(nodeExecutable,[registryPath,'run','--owner','GPT','--name',name,'--desc',kind === 'gateway' ? '录音记忆材料网关' : kind === 'context' ? '录音记忆自动情景' : kind === 'visual' ? '录音记忆录像分析' : kind === 'camera' ? '录音记忆手机采集' : '录音记忆录音与转写','--',python,...command],{
          cwd:projectRoot,windowsHide:true,stdio:['ignore',log,log],env:{...process.env,...cloudEnv,ELECTRON_RUN_AS_NODE:'1',AUDIO_MEMORY_PROCESS_REGISTRY_DIR:registryDir,PYTHONUTF8:'1'}
        });
      } finally { fs.closeSync(log); }
      let spawnError = null; processHandle.once('error', error => { spawnError = error; });
      for (let i=0;i<100;i++) {
        if (spawnError || !alive()) {
          clear();
          return { status:'error', message:kind === 'gateway' ? '网关启动失败，请查看日志' : kind === 'context' ? '情景启动失败或已经运行，请查看日志' : kind === 'visual' ? '录像处理启动失败或已经运行，请查看日志' : kind === 'camera' ? '手机接收启动失败，请检查课堂模式和日志' : '录音启动失败，请查看日志' };
        }
        if (kind === 'recording' && !fs.existsSync(path.join(stopDirectory,'parent-registered'))) {
          try {
            const registry = JSON.parse(fs.readFileSync(path.join(registryStore,'process-registry.json'),'utf8'));
            if (registry.processes.some(entry => entry.name === name && entry.status === 'running' && Number.isInteger(entry.pid) && entry.pid > 0))
              fs.writeFileSync(path.join(stopDirectory,'parent-registered'),'ready');
          } catch {}
        }
        if (kind === 'gateway' && (await readTranscripts(root)).status === 'ready') return { status:'owned' };
        if (kind !== 'gateway' && fs.existsSync(path.join(stopDirectory,'ready'))) return {status:'owned'};
        await delay(100);
      }
      await stop();
      return { status:'error', message:kind === 'gateway' ? '网关启动超时，请查看日志' : kind === 'context' ? '情景启动超时，请查看日志' : kind === 'visual' ? '录像处理启动超时，请查看日志' : kind === 'camera' ? '手机接收启动超时，请查看日志' : '未收到麦克风音频，请检查设备和日志' };
    } finally { starting=false; }
  }
  async function stop() {
    if (!processHandle) return { status:'stopped' };
    if (!alive()) return completed();
    fs.writeFileSync(path.join(stopDirectory,'stop'),'stop');
    const exited = await new Promise(resolve => {
      const timer = setTimeout(() => resolve(false),kind === 'recording' ? 180000 : kind === 'context' ? 100000 : kind === 'visual' ? 45000 : 10000);
      processHandle.once('exit', () => { clearTimeout(timer); resolve(true); });
    });
    if (!exited) return { status:'error',message:kind === 'gateway' ? '网关仍在停止，请稍后检查日志' : kind === 'context' ? '情景仍在停止，请稍后检查日志' : kind === 'visual' ? '录像处理仍在停止，请稍后检查日志' : '录音仍在保存，请稍后检查日志' };
    return completed();
  }
  return { start, stop, isOwned: alive, isReady: () => alive() && !!stopDirectory && fs.existsSync(path.join(stopDirectory,'ready')) };
}
module.exports = { createServiceController };
