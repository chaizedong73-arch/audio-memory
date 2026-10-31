import fs from 'node:fs';
import path from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {pathToFileURL} from 'node:url';

const [action,file,runtime]=process.argv.slice(2);
try{
 if(!runtime)throw Error('缺少录音记忆运行目录；请先在工作台中绑定项目目录');
 const projectRoot=path.resolve(runtime);
 const integrations=JSON.parse(fs.readFileSync(path.join(projectRoot,'config/integrations.json'),'utf8'));
 if(!integrations.toolboxRoot)throw Error('请在 config/integrations.json 配置 toolboxRoot');
 const adapterRoot=path.join(integrations.toolboxRoot,'modules/collaboration-canvas');
 if(action==='sessions'){
  const db=new DatabaseSync(path.join(process.env.USERPROFILE,'.workbuddy/workbuddy.db'),{readOnly:true});
  try{
   const sessions=db.prepare('SELECT id,title,custom_title,model,cwd,status FROM sessions WHERE deleted_at IS NULL ORDER BY updated_at DESC').all().map(s=>{
    let cached={};try{cached=JSON.parse(fs.readFileSync(path.join(adapterRoot,'data/workbuddy-dispatch','capabilities-'+s.id+'.json'),'utf8'));}catch{}
    const available=cached.models?.availableModels||[{modelId:s.model,name:s.model}];
    return {id:s.id,name:s.custom_title||s.title||s.id,model:s.model,cwd:s.cwd,status:s.status,models:[{id:'',label:'沿用会话模型（'+s.model+'）'},...available.filter(m=>m.modelId).map(m=>({id:m.modelId,label:m.name||m.modelId}))]};
   });
   fs.writeFileSync(file,JSON.stringify(sessions));
  }finally{db.close();}
 }else if(action==='send'){
  const mode=JSON.parse(fs.readFileSync(path.join(projectRoot,'classroom-mode.json'),'utf8'));
  if(mode.enabled!==true)throw Error('上课模式已关闭，未提交笔记维护任务');
  const adapter=path.join(adapterRoot,'workbuddy-dispatch.mjs');
  if(!fs.existsSync(adapter))throw Error('课堂维护需要安装多AI协同基站的WorkBuddy会话通道；本地录音和转写不受影响');
  const {dispatch,readWindow}=await import(pathToFileURL(adapter).href);
  const job=JSON.parse(fs.readFileSync(file,'utf8'));
  const window=readWindow(job.sessionId);
  const lock=path.join(adapterRoot,'data/workbuddy-dispatch','window-'+window.id+'.lock');
  if(!['idle','completed'].includes(window.status)||fs.existsSync(lock)){console.log(JSON.stringify({state:'busy'}));process.exitCode=2;}
  else{
   if(JSON.parse(fs.readFileSync(path.join(projectRoot,'classroom-mode.json'),'utf8')).enabled!==true)throw Error('上课模式已关闭，未派工');
   const result=await dispatch(job);
   console.log(JSON.stringify({state:result.state,historyConfirmed:result.historyConfirmed,jobId:result.jobId,replyFile:result.replyFile,error:result.error,pendingPermission:result.pendingPermission,cleanupError:result.cleanupError}));
   if(result.state!=='finished'||!result.historyConfirmed||result.cleanupError)process.exitCode=1;
  }
 }else throw Error('未知课堂维护操作');
}catch(error){console.error(error.message);process.exitCode=1;}
