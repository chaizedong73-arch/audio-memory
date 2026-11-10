import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type MobileSyncState={status:string;pairings:{address:string;interface?:string;code:string}[];remote?:{status:string;code?:string;origin?:string;message?:string}};
type UsageBucket = {calls:number;estimatedYuan:number;unknown:number};
type UsageResult = {status:string;today:UsageBucket;total:UsageBucket;warnings:number;message?:string;items:{id:string;time:string;file:string;model:string;audioSeconds:number;inputTokens:number|null;outputTokens:number|null;estimatedYuan:number|null;status:string}[]};
type Item = { id: string; version: string; revision: number; text: string; time: string; source: string };
type CorrectionResult = {status: 'ready' | 'error' | 'offline' | 'stale'; message?: string; changed?: boolean; warnings?: string[]};
type Action = { status: string; message?: string; url?:string; model?:string; errors?:{name:string;message:string}[] };
type ClassroomStatus = {active:boolean; recording:{owned:boolean;ready:boolean};context:boolean;camera:boolean;visual:boolean;gateway:boolean};
type Result = { status: 'offline' | 'error' | 'ready' | 'stale'; items: Item[]; total: number; snapshot: string; nextOffset: number | null };
type ContextCandidate = { createdAt?: number; candidate?: { sixElements?: Record<string, {value?: string; sources?: string[]}>; narrative?: string; uncertainties?: string[] }; sources?: {id?: string; text?: string}[] };
type VisualTask = {source?: string; stage?: string; pages?: number; error?: string; warning?: string; alignmentWarnings?: string[]; indexWarning?:string; gatewayWarning?:string};
type VisualResult = {status:'ready' | 'offline' | 'error'; tasks:VisualTask[]};
type CameraResult = {status:string; message?:string; connected?:boolean; recording?:boolean; phone?:string; error?:string; preview?:string; latestPage?:string; ocrText?:string; ocrState?:string; ppt?:{count?:number;message?:string;ocrCompleted?:number;ocrPending?:number;ocrError?:string}; remote?:{status:string;message?:string;url?:string;captureQr?:string}|null; wifi?:{ip?:string; fingerprint?:string; certificateQr?:string; captureQr?:string}|null};
type ContextResult = { status: 'offline' | 'error' | 'ready'; state: {status?: string; message?: string}; candidate: ContextCandidate | null };
declare global { interface Window { audioMemory: { readTranscripts(options?: {offset?: number; snapshot?: string; day?: string}): Promise<Result>; refreshTranscripts(options?: {day?: string}): Promise<Result>; correctTranscript(value: {id:string; snapshot:string; contentVersion:string; text:string}): Promise<CorrectionResult>; readContext(): Promise<ContextResult>; startClassroom(): Promise<Action>; stopClassroom(): Promise<Action>; classroomStatus(): Promise<ClassroomStatus>; startCamera(): Promise<Action>; cameraStatus(): Promise<CameraResult>; cameraWifi(): Promise<Action>; cameraRemote(): Promise<Action>; cameraRemoteStop(): Promise<Action>; cameraUsb(): Promise<Action>; cameraCommand(name:'record'|'preview'|'snapshot'): Promise<Action>; stopCamera(): Promise<Action>; readVisual(): Promise<VisualResult>; startVisual(): Promise<Action>; stopVisual(): Promise<Action>; visualStatus(): Promise<boolean>; importVideo(): Promise<Action & {name?:string}>; startGateway(): Promise<Action>; stopGateway(): Promise<Action>; startContext(): Promise<Action>; stopContext(): Promise<Action>; contextStatus(): Promise<boolean>; startMobileSync():Promise<Action>; stopMobileSync():Promise<Action>; mobileSyncRemote(stop?:boolean):Promise<{status:string;code?:string;origin?:string;message?:string}>; mobileSyncStatus():Promise<MobileSyncState>; copyMobilePairing(code:string):Promise<boolean>; readUsage(): Promise<UsageResult>; readAsrProvider(): Promise<{mode?:'local'|'cloud'|'legacy';configured:boolean;url?:string;model?:string;protocol?:string;message?:string;legacyAvailable?:boolean}>; saveAsrProvider(value:{url:string;model:string;protocol:string;key:string}): Promise<Action>; setTranscriptionMode(mode:'local'|'cloud'|'legacy'): Promise<Action>; startRecording(): Promise<Action>; stopRecording(): Promise<Action>; recordingStatus(): Promise<{owned:boolean;ready:boolean}>; openLogs(): Promise<string>; onClosing(callback: () => void): () => void } } }
const display = (value: unknown, fallback = '未知') => typeof value === 'string' && value.trim() ? value : fallback;
const elements = [['time','时间'],['place','地点'],['people','人物'],['cause','起因'],['process','经过'],['result','结果']];

function localDay() { const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }

function App() {
  const [workspace, setWorkspace] = useState<'normal'|'classroom'>('normal');
  const [page, setPage] = useState<'transcripts' | 'context' | 'recording' | 'visual'>('transcripts');
  const [result, setResult] = useState<Result | null>(null);
  const [classroom, setClassroom] = useState<ClassroomStatus | null>(null);
  const [camera, setCamera] = useState<CameraResult>({status:'offline'});
  const [visual, setVisual] = useState<VisualResult | null>(null);
  const [visualOwned, setVisualOwned] = useState(false);
  const [context, setContext] = useState<ContextResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [owned, setOwned] = useState(false);
  const [contextOwned, setContextOwned] = useState(false);
  const [provider, setProvider] = useState({url:'',model:'',protocol:'ark_audio',key:''});
  const [mobileSyncBusy,setMobileSyncBusy]=useState(false);
  const [mobileSync,setMobileSync]=useState<MobileSyncState>({status:'stopped',pairings:[]});
  const mobileSyncAction=async()=>{setMobileSyncBusy(true);try{const r=mobileSync.status==='ready'?await window.audioMemory.stopMobileSync():await window.audioMemory.startMobileSync();setNotice(r.message || (r.status==='error'?'手机接收启动失败，请查看日志。':''));setMobileSync(await window.audioMemory.mobileSyncStatus());}catch{setNotice('手机同步操作失败，请查看日志。');}finally{setMobileSyncBusy(false);}};
  const mobileRemoteAction=async()=>{setMobileSyncBusy(true);setNotice('正在建立或关闭远程同步连接，请稍候…');try{const r=await window.audioMemory.mobileSyncRemote(mobileSync.remote?.status==='ready');const state=await window.audioMemory.mobileSyncStatus();setMobileSync({...state,remote:r});setNotice(r.status==='ready'?'远程同步已开启，请将新配对码粘贴到手机。':r.status==='stopped'?'远程同步已关闭，旧配对码失效。':r.message||'远程同步失败，请重试。');}catch{setNotice('远程同步操作失败，请重试。');}finally{setMobileSyncBusy(false);}};
  useEffect(()=>{if(page!=='recording')return;const update=()=>void window.audioMemory.mobileSyncStatus().then(setMobileSync).catch(()=>{});update();const timer=window.setInterval(update,5000);return()=>window.clearInterval(timer);},[page]);
  const [usage,setUsage] = useState<UsageResult|null>(null);
  const [usageError,setUsageError] = useState('');
  const refreshUsage = useCallback(async()=>{try{const r=await window.audioMemory.readUsage();setUsage(r);setUsageError(r.status==='ready'?'':r.message || '费用读取失败');}catch{setUsageError('费用读取失败，请重试。');}},[]);
  useEffect(()=>{if(page!=='recording')return;void refreshUsage();const timer=window.setInterval(()=>void refreshUsage(),10000);return ()=>window.clearInterval(timer);},[page,refreshUsage]);
  const [providerNotice, setProviderNotice] = useState('');
  const [legacyAvailable, setLegacyAvailable] = useState(false);
  const [savedProvider, setSavedProvider] = useState<{url:string;model:string;protocol:string}|null>(null);
  const [providerConfigured, setProviderConfigured] = useState(false);
  const [transcriptionMode, setTranscriptionMode] = useState<'local'|'cloud'|'legacy'>('local');
  const [recording, setRecording] = useState({owned:false,ready:false});
  const [closing, setClosing] = useState(false);
  const [notice, setNotice] = useState('');
  const [offset, setOffset] = useState(0);
  const [selectedDay, setSelectedDay] = useState(localDay);
  const [followToday, setFollowToday] = useState(true);
  const dayRef = useRef(selectedDay);
  const [editing, setEditing] = useState<Item | null>(null);
  const [draft, setDraft] = useState('');
  const [editNotice, setEditNotice] = useState('');
  const refresh = useCallback(async (rebuild = false, nextOffset = 0, snapshot = '') => {
    setLoading(true);
    try {
      const day=dayRef.current;
      const next = rebuild ? await window.audioMemory.refreshTranscripts({day}) : await window.audioMemory.readTranscripts({offset:nextOffset,snapshot,day});
      if (dayRef.current !== day) return;
      setResult(next); if (next.status === 'ready') setOffset(rebuild ? 0 : nextOffset);
    } catch { setResult({ status: 'error', items: [], total: 0, snapshot: '', nextOffset: null }); }
    finally { setLoading(false); }
  }, []);
  const refreshContext = useCallback(async () => {
    setLoading(true);
    try { setContext(await window.audioMemory.readContext()); }
    catch { setContext({status:'error',state:{},candidate:null}); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { let active=true; (async()=>{setLoading(true);try{const started=await window.audioMemory.startGateway();if(!active)return;setOwned(started.status==='owned');if(started.status==='error')setNotice(started.message || '资料连接失败，请重试。');await refresh();}catch{if(active)setNotice('资料连接失败，请重试。');}finally{if(active)setLoading(false);}})(); return ()=>{active=false;}; }, [refresh]);
  useEffect(() => { if(page !== 'transcripts' || editing || offset !== 0 || !recording.owned) return; let alive=true, busy=false; const timer=window.setInterval(async()=>{if(busy)return;busy=true;try {const day=dayRef.current;const next=await window.audioMemory.refreshTranscripts({day});if(alive && dayRef.current===day && next.status==='ready')setResult(next);}catch{}finally{busy=false;}},10000);return ()=>{alive=false;window.clearInterval(timer);}; },[page,editing,offset,recording.owned]);
  const chooseDay = (day:string, follow:boolean) => { dayRef.current=day; setSelectedDay(day); setFollowToday(follow); setOffset(0); setResult(null); void refresh(); };
  useEffect(() => {
    const update=()=>{const today=localDay();if(followToday && !editing && dayRef.current!==today)chooseDay(today,true);};
    update();const timer=window.setInterval(update,30000);window.addEventListener('focus',update);
    return ()=>{window.clearInterval(timer);window.removeEventListener('focus',update);};
  },[followToday,editing]);
  useEffect(() => { if (page === 'context') void refreshContext(); if (page === 'visual') void window.audioMemory.readVisual().then(setVisual); }, [page, refreshContext]);
  useEffect(() => { if (page !== 'visual' || !visualOwned) return; const timer = window.setInterval(() => { void window.audioMemory.readVisual().then(setVisual); void window.audioMemory.visualStatus().then(active => {if (!active) {setVisualOwned(false);setNotice('录像处理已停止，请查看日志。');}}); }, 5000); return () => window.clearInterval(timer); }, [page, visualOwned]);
  useEffect(() => window.audioMemory.onClosing(() => { setClosing(true); setNotice('正在等待正在处理的任务完成并停止…'); }), []);
  useEffect(() => {
    if (page !== 'context' || !contextOwned) return;
    const timer = window.setInterval(() => {
      void window.audioMemory.readContext().then(setContext).catch(() => {});
      void window.audioMemory.contextStatus().then(active => { if (!active) { setContextOwned(false); setNotice('自动情景已停止，请查看日志。'); } }).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [page, contextOwned]);
  useEffect(() => {
    if (!recording.owned) return;
    const timer = window.setInterval(() => { void window.audioMemory.recordingStatus().then(state => {
      setRecording(state); if (!state.owned) setNotice('录音已停止，请查看日志。');
    }).catch(() => {}); }, 2000);
    return () => window.clearInterval(timer);
  }, [recording.owned]);
  const ready = result?.status === 'ready';
  const online = page === 'context' ? context?.status === 'ready' : ready || result?.status === 'stale';
  const selectedStatus = page === 'visual' || page === 'recording' ? 'ready' : page === 'context' ? context?.status : result?.status;
  const startGateway = async () => {
    setLoading(true); setNotice('');
    try { const r = await window.audioMemory.startGateway(); setOwned(r.status === 'owned'); if(r.message) setNotice(r.message); if(page === 'context') await refreshContext(); else if(page === 'visual') { await refresh(); setVisual(await window.audioMemory.readVisual()); } else await refresh(); }
    catch { setNotice('启动失败，请查看日志。'); } finally { setLoading(false); }
  };
  const stopGateway = async () => {
    setLoading(true); setNotice('');
    try { const r = await window.audioMemory.stopGateway(); if(r.message) setNotice(r.message); if(r.status === 'stopped') setOwned(false); if(page === 'context') await refreshContext(); else if(page === 'visual') { await refresh(); setVisual(await window.audioMemory.readVisual()); } else await refresh(); }
    catch { setNotice('停止失败，请查看日志。'); } finally { setLoading(false); }
  };
  const startContext = async () => {
    setLoading(true); setNotice('');
    try { const r = await window.audioMemory.startContext(); setContextOwned(r.status === 'owned'); if(r.message) setNotice(r.message); await refreshContext(); }
    catch { setNotice('自动情景启动失败，请查看日志。'); } finally { setLoading(false); }
  };
  const stopContext = async () => {
    setLoading(true); setNotice('正在等待当前请求结束…');
    try { const r = await window.audioMemory.stopContext(); if(r.status === 'stopped') { setContextOwned(false); setNotice('自动情景已停止'); } else setNotice(r.message || '情景停止失败'); await refreshContext(); }
    catch { setNotice('自动情景停止失败，请查看日志。'); } finally { setLoading(false); }
  };
  const saveCorrection = async () => {
    if (!editing || !result?.snapshot || !draft.trim()) return;
    setLoading(true); setEditNotice('');
    try {
      const saved=await window.audioMemory.correctTranscript({id:editing.id,snapshot:result.snapshot,contentVersion:editing.version,text:draft});
      if(saved.status !== 'ready') { setEditNotice(saved.message || '修订失败，草稿已保留。'); return; }
      setEditing(null); setDraft(''); setEditNotice(saved.warnings?.join('；') || (saved.changed ? '修订已保存，原始字幕保留。' : '内容未改变。'));
      await refresh();
    } catch { setEditNotice('修订失败，草稿已保留。'); } finally { setLoading(false); }
  };
  useEffect(() => {void window.audioMemory.readAsrProvider().then(p=>{if(p.mode)setTranscriptionMode(p.mode);setLegacyAvailable(Boolean(p.legacyAvailable));if(p.configured){setProviderConfigured(true);setSavedProvider({url:p.url || '',model:p.model || '',protocol:p.protocol || 'ark_audio'});setProvider({url:p.url || '',model:p.model || '',protocol:p.protocol || 'ark_audio',key:''});}else if(p.message){setProviderNotice(p.message);setNotice(p.message);}});},[]);
  const saveProvider = async () => {setProviderNotice('正在保存…');try {const r=await window.audioMemory.saveAsrProvider(provider);if(r.status==='ready'){setProviderConfigured(true);setSavedProvider({url:r.url || provider.url,model:r.model || provider.model,protocol:provider.protocol});setProvider(p=>({...p,url:r.url || p.url,model:r.model || p.model,key:''}));setProviderNotice('配置已保存。密钥已加密保存，留空表示继续使用已保存的密钥。');}else setProviderNotice(r.message || '保存失败，请检查输入。');}catch{setProviderNotice('保存失败，请重试。');}};
  const changeTranscriptionMode = async (mode:'local'|'cloud'|'legacy') => {
    setLoading(true);setNotice(recording.owned ? '正在保存当前录音并切换转写方式，期间会短暂停顿…' : '正在切换转写方式…');
    try {const r=await window.audioMemory.setTranscriptionMode(mode);
      if(r.status==='ready'){setTranscriptionMode(mode);setNotice(mode!=='local'?'已选择云端转写：录音会发送至所选服务。':'已选择本地转写。');}
      else setNotice(r.message || '切换失败');
      setRecording(await window.audioMemory.recordingStatus());
    }catch{setNotice('切换失败，请检查录音状态和日志。');}finally{setLoading(false);}
  };
  const startRecording = async () => {
    setLoading(true); setNotice('正在连接麦克风…');
    try { const r = await window.audioMemory.startRecording(); setRecording(await window.audioMemory.recordingStatus()); setNotice(r.message || ''); }
    catch { setNotice('录音启动失败，请查看日志。'); } finally { setLoading(false); }
  };
  const stopRecording = async () => {
    setLoading(true); setNotice('正在保存录音并处理剩余音频，请稍候…');
    try { const r = await window.audioMemory.stopRecording(); setRecording(await window.audioMemory.recordingStatus()); setNotice(r.message || '录音已保存并停止'); }
    catch { setNotice('录音停止失败，请查看日志。'); } finally { setLoading(false); }
  };
  useEffect(() => { if (camera.status !== 'ready') return; const timer=window.setInterval(() => {void window.audioMemory.cameraStatus().then(setCamera);}, 3000); return () => window.clearInterval(timer); }, [camera.status]);
  const cameraAction = async (action:'start'|'stop'|'wifi'|'remote'|'remote-stop'|'usb'|'record'|'preview'|'snapshot') => {
    setLoading(true);setNotice(action==='remote' ? '正在建立远程连接，首次可能需要一分钟…' : '');
    try { const r=action==='start' ? await window.audioMemory.startCamera() : action==='stop' ? await window.audioMemory.stopCamera() : action==='wifi' ? await window.audioMemory.cameraWifi() : action==='remote' ? await window.audioMemory.cameraRemote() : action==='remote-stop' ? await window.audioMemory.cameraRemoteStop() : action==='usb' ? await window.audioMemory.cameraUsb() : await window.audioMemory.cameraCommand(action);
      setNotice(r.message || (r.status==='error' ? '采集操作失败，请查看日志。' : ''));setCamera(await window.audioMemory.cameraStatus());
    } catch {setNotice('采集操作失败，请查看日志。');} finally {setLoading(false);}
  };
  const syncClassroom = async () => {const state=await window.audioMemory.classroomStatus();setClassroom(state);setRecording(state.recording);setContextOwned(state.context);setVisualOwned(state.visual);setOwned(state.gateway);setCamera(await window.audioMemory.cameraStatus());};
  const classroomAction = async () => {
    setLoading(true);setNotice(classroom?.active ? '正在结束课堂并保存…' : '正在启动课堂…');
    try {const r=classroom?.active ? await window.audioMemory.stopClassroom() : await window.audioMemory.startClassroom();await syncClassroom();
      const names:Record<string,string>={gateway:'材料网关',visual:'录像分析',context:'情景',camera:'手机采集',recording:'录音'};
      setNotice(r.message || (r.errors?.length ? r.errors.map(e=>`${names[e.name] || e.name}：${e.message}`).join('；') : r.status==='stopped' ? '课堂已结束' : r.status==='active' ? '课堂已启动' : '操作未完成，请查看日志'));
    } catch {setNotice('课堂操作失败，请查看日志。');}finally{setLoading(false);}
  };
  const visualAction = async (action: 'start' | 'stop' | 'import') => {
    setLoading(true); setNotice('');
    try {
      const r = action === 'start' ? await window.audioMemory.startVisual() : action === 'stop' ? await window.audioMemory.stopVisual() : await window.audioMemory.importVideo();
      let automaticError = '';
      if (action === 'start' || (action === 'import' && r.status === 'ready')) {
        if (action === 'import') { const started = await window.audioMemory.startVisual(); if (started.message) automaticError = started.message; }
        const gateway = await window.audioMemory.startGateway();
        if (gateway.status === 'owned') setOwned(true);
        if (gateway.message) automaticError = [automaticError, gateway.message].filter(Boolean).join('；');
        await refresh();
      }
      if (action !== 'import' || r.status === 'ready') setVisualOwned(await window.audioMemory.visualStatus());
      setNotice(r.message || automaticError || (action === 'import' && r.status === 'ready' ? '录像已导入，正在启动处理；原文件保留。' : action === 'stop' && r.status === 'stopped' ? '录像处理已停止，下次可继续。' : ''));
      setVisual(await window.audioMemory.readVisual());
    } catch { setNotice('操作失败，请查看日志。'); } finally { setLoading(false); }
  };
  const openLogs = async () => { try { const error=await window.audioMemory.openLogs(); if(error) setNotice('无法打开日志目录。'); } catch { setNotice('无法打开日志目录。'); } };
  const title = page === 'visual' ? 'PPT采集' : page === 'recording' ? '录音' : page === 'context' ? '情景' : '字幕';
  const content = context?.candidate?.candidate;
  return <div className="layout">
    <aside className="sidebar">
      <div className="brand"><span className="brand-icon">◉</span><div><strong>录音记忆</strong><small>材料工作台</small></div></div>
      <div className="section-label">模式</div>
      <div className="workspace-switch" role="group" aria-label="工作模式"><button className={workspace==='normal' ? 'workspace-active' : ''} onClick={() => {setWorkspace('normal');if(page==='visual')setPage('recording');}}>常规模式</button><button className={workspace==='classroom' ? 'workspace-active' : ''} onClick={() => setWorkspace('classroom')}>{classroom?.active ? '上课中' : '上课模式'}</button></div>
      <div className="section-label">{workspace==='classroom' ? '课堂工作区' : '常规工作区'}</div>
      {workspace==='classroom' && <button className="nav-item" disabled={loading || closing} onClick={() => void classroomAction()}><span>▶</span> {classroom?.active ? '结束课堂' : '开始课堂'}</button>}
      <button className={'nav-item ' + (page === 'recording' ? 'nav-active' : '')} onClick={() => setPage('recording')}><span>◉</span> 录音</button>
      <button className={'nav-item ' + (page === 'transcripts' ? 'nav-active' : '')} onClick={() => setPage('transcripts')}><span>▤</span> 字幕</button>
      {workspace==='classroom' && <button className={'nav-item ' + (page === 'visual' ? 'nav-active' : '')} onClick={() => setPage('visual')}><span>▣</span> PPT采集</button>}
      <button className={'nav-item ' + (page === 'context' ? 'nav-active' : '')} onClick={() => setPage('context')}><span>◷</span> 情景</button>
      <div className="sidebar-footer"><span className={online ? 'dot online' : 'dot'} />{online ? '资料已连接' : '资料未连接'}</div>
    </aside>
    <main>
      <header><div className="breadcrumb">录音记忆 <span>/</span> {title}</div><button onClick={() => void (page === 'visual' ? window.audioMemory.refreshTranscripts().then(async () => setVisual(await window.audioMemory.readVisual())) : page === 'recording' ? window.audioMemory.recordingStatus().then(setRecording) : page === 'context' ? refreshContext() : refresh(true))} disabled={loading || (page === 'transcripts' && !!editing)}>{loading ? '读取中…' : '刷新'}</button></header>
      <div className="content">{notice && <div className="closing-notice">{notice}</div>}{closing && <div className="closing-notice">正在等待任务结束并停止，请稍候。</div>}<div className="intro"><div><div className="eyebrow">{page === 'visual' ? 'VIDEO' : page === 'recording' ? 'RECORDING' : page === 'context' ? 'CONTEXT' : 'TRANSCRIPT'}</div><h1>{title}</h1><p>{page === 'visual' ? '自动截取 PPT 并识别文字，可对照页面核验' : page === 'recording' ? '保存音频，并在后台转写和登记材料' : page === 'context' ? '按六要素还原当前发生的事情' : '查看已保存并登记的转写内容'}</p></div>{page === 'transcripts' && ready && <div className="count"><strong>{result.total}</strong><span>条字幕</span></div>}</div>
        {page === 'transcripts' && editNotice && !editing && !ready && <div className="closing-notice">{editNotice}</div>}
        {!selectedStatus && <div className="empty">正在读取…</div>}
        {selectedStatus === 'offline' && <div className="empty"><div className="empty-icon">◌</div><h2>资料暂时不可用</h2><p>请稍后重试连接。</p><button className="primary" onClick={() => void startGateway()} disabled={loading}>{loading ? '正在连接…' : '重试连接'}</button>{notice && <p className="notice">{notice}</p>}</div>}
        {selectedStatus === 'stale' && <div className="empty"><h2>字幕已更新</h2><p>点击刷新后重新查看。</p></div>}
        {selectedStatus === 'error' && <div className="empty"><h2>读取失败</h2><p>请重试连接或查看日志。</p></div>}
        {page === 'visual' && <section className="ppt-page"><div className="ppt-card"><div className="ppt-heading"><div><h2>手机现场采集</h2><p>{camera.status==='ready' ? camera.connected ? '手机已连接 · 正在采集 PPT' : '等待手机连接' : '启动后连接手机采集画面'}</p>{camera.ppt && <p>已提取 {camera.ppt.count || 0} 页 · 已识别 {camera.ppt.ocrCompleted || 0} 页 · 待识别 {camera.ppt.ocrPending || 0} 页</p>}{(camera.ppt?.ocrError || camera.error) && <p className="ppt-error">{camera.ppt?.ocrError || camera.error}</p>}</div><div className="ppt-actions">{camera.status==='ready' ? <><button disabled={loading} onClick={() => void cameraAction('remote')}>远程配对</button><button disabled={loading} onClick={() => void cameraAction('wifi')}>Wi-Fi 配对</button><button disabled={loading} onClick={() => void cameraAction('usb')}>USB 连接</button><button disabled={loading} onClick={() => void cameraAction('stop')}>结束采集</button></> : <button className="primary" disabled={loading} onClick={() => void cameraAction('start')}>启动手机采集</button>}</div></div>{camera.remote && <div className="ppt-pairing"><h3>远程连接</h3><p>{camera.remote.message}</p>{camera.remote.status==='ready' && <><img width="220" alt="远程采集二维码" src={camera.remote.captureQr}/><p>使用手机系统浏览器扫码并允许摄像头。画面经互联网中转后保存在电脑，结束采集后连接失效。</p><button disabled={loading} onClick={() => void cameraAction('remote-stop')}>关闭远程连接</button></>}</div>}{camera.wifi && <div className="ppt-pairing"><h3>Wi-Fi 连接</h3><p>手机与电脑连接同一 Wi-Fi，先安装证书，再打开采集页面。</p><div className="ppt-qr-grid"><div><strong>1. 安装证书</strong><img width="160" alt="证书二维码" src={camera.wifi.certificateQr}/></div><div><strong>2. 打开采集</strong><img width="160" alt="采集二维码" src={camera.wifi.captureQr}/></div></div><details><summary>查看证书指纹</summary><code>{camera.wifi.fingerprint}</code></details></div>}{camera.preview && <div className="ppt-preview"><h3>手机画面</h3><img alt="手机画面" src={camera.preview}/></div>}</div><div className="ppt-card ppt-result"><div className="ppt-result-heading"><h2>最近识别的 PPT</h2><span>{camera.ocrState || '等待截取页面'}</span></div>{camera.latestPage ? <img className="ppt-latest" alt="截取的 PPT 页面" src={camera.latestPage}/> : <p className="ppt-empty">采集到页面后，截图和识别文字会显示在这里。</p>}{camera.ocrText && <div className="ppt-ocr"><h3>识别文字</h3><p>{camera.ocrText}</p></div>}</div></section>}

        {page === 'recording' && <section className="recording-page"><div className="record-card recording-main"><div className="record-indicator"><span className={recording.ready ? 'record-dot active' : 'record-dot'} /><div><h2>{recording.owned ? recording.ready ? '正在接收音频' : '等待麦克风恢复' : '准备开始录音'}</h2><p>{recording.owned ? '音频会分段保存，转写结果自动更新。' : '使用本机麦克风，音频将分段保存。'}</p></div></div><div className="record-actions">{recording.owned ? <button className="record-stop" disabled={loading || closing} onClick={() => void stopRecording()}>{loading ? '正在停止…' : '停止并保存'}</button> : <button className="record-start primary" disabled={loading || closing} onClick={() => void startRecording()}>{loading ? '正在启动…' : '开始录音'}</button>}<button className="logs-button" onClick={() => void openLogs()}>打开日志</button></div></div><div className="record-settings"><div className="record-settings-head"><div><h2>转写设置</h2><p>录音中也可切换：先保存当前音频，再继续录音，期间会短暂停顿。</p></div><label className="mode-field"><span>转写方式</span><select aria-label="音频转写方式" value={transcriptionMode} disabled={closing || loading} onChange={event => void changeTranscriptionMode(event.target.value as 'local'|'cloud'|'legacy')}><option value="local">本地 · Whisper</option>{legacyAvailable && <option value="legacy">火山方舟 · 豆包 Seed 2.0 mini（本机已有）</option>}{savedProvider && <option value="cloud">{savedProvider.protocol==='ark_audio' ? '火山方舟' : '兼容转写接口'} · {savedProvider.model}</option>}</select></label></div><div className="provider-list"><strong>转写服务</strong><div className="provider-row"><span>本地 Whisper</span><small>{transcriptionMode==='local' ? '当前选择 · ' : ''}本机运行</small></div>{legacyAvailable && <div className="provider-row"><span>火山方舟 · 豆包 Seed 2.0 mini</span><small>{transcriptionMode==='legacy' ? '当前选择 · ' : ''}本机已有配置</small></div>}{savedProvider && <div className="provider-row"><span>{savedProvider.model}</span><small>{transcriptionMode==='cloud' ? '当前选择 · ' : ''}{savedProvider.protocol==='ark_audio' ? '火山方舟接口' : '兼容语音转写接口'} · 已保存</small></div>}</div><details className="provider-details"><summary>云端转写服务 <span>{providerConfigured ? '已配置' : '未配置'}</span></summary><div className="provider-content"><p>填写支持音频转写的服务地址和模型，密钥会加密保存在本机。</p><div className="provider-grid"><label><span>接口协议</span><select aria-label="接口协议" value={provider.protocol} onChange={e=>setProvider({...provider,protocol:e.target.value})}><option value="ark_audio">火山方舟音频对话接口</option><option value="openai_transcription">OpenAI 兼容语音转写接口</option></select></label><label><span>模型名称</span><input aria-label="模型名称" placeholder="输入模型名称" value={provider.model} onChange={e=>setProvider({...provider,model:e.target.value})}/></label><label className="provider-wide"><span>API 地址</span><input aria-label="API 地址" placeholder="https://服务地址/v1" value={provider.url} onChange={e=>setProvider({...provider,url:e.target.value})}/></label><label className="provider-wide"><span>API 密钥</span><input aria-label="API 密钥" type="password" placeholder={providerConfigured ? '已保存密钥；留空保持不变' : '输入 API 密钥'} value={provider.key} onChange={e=>setProvider({...provider,key:e.target.value})}/></label></div><div className="provider-footer"><span className="provider-feedback" role="status">{providerNotice}</span><button disabled={loading || recording.owned} onClick={() => void saveProvider()}>保存配置</button></div></div></details></div></section>}
        {page === 'recording' && <section className="usage-card mobile-sync-card"><div className="usage-heading"><div><h2>手机同步接收</h2><p>安卓手机保留原件，可通过互联网远程同步，也可使用同一 Wi-Fi。</p></div><button disabled={mobileSyncBusy||closing} onClick={()=>void mobileSyncAction()}>{mobileSync.status==='ready'?'关闭接收':'开启接收'}</button></div>{mobileSync.status==='ready' && <><div className="mobile-remote"><button disabled={mobileSyncBusy||closing} onClick={()=>void mobileRemoteAction()}>{mobileSync.remote?.status==='ready'?'关闭远程同步':'开启远程同步'}</button><p className="usage-note">远程同步不要求同一 Wi-Fi，录音、字幕和费用记录经 Cloudflare 中转；关闭接收后通道失效。</p>{mobileSync.remote?.status==='ready'&&<div className="mobile-pairing"><strong>远程连接已就绪</strong><button onClick={()=>void window.audioMemory.copyMobilePairing(mobileSync.remote!.code!).then(ok=>setNotice(ok?'远程配对码已复制。':'复制失败，请重新开启远程同步。'))}>复制远程配对码</button></div>}</div><p className="usage-note">下方为同一 Wi-Fi 的局域网配对。在手机“同步”页粘贴配对码。配对码允许向本机上传录音，请只交给自己的设备。</p>{mobileSync.pairings.length===0&&<p className="notice">未找到局域网地址，请连接 Wi-Fi 后重新开启。</p>}{mobileSync.pairings.map(p=><div className="mobile-pairing" key={p.address}><div><strong>{p.address}</strong><small className="mobile-network">{p.interface}</small></div><button onClick={()=>void window.audioMemory.copyMobilePairing(p.code).then(ok=>setNotice(ok?'配对码已复制。':'复制失败，请重新开启接收。'))}>复制配对码</button></div>)}</>}</section>}
        {page === 'recording' && <section className="usage-card" aria-label="云端转写费用"><div className="usage-heading"><div><h2>云端转写费用</h2><p>按接口返回用量估算，不等于实际扣费；本地转写不产生云端调用费。</p></div><button onClick={()=>void refreshUsage()}>刷新费用</button></div>{usageError && <p className="notice" role="alert">{usageError}</p>}{usage?.status==='ready' && <><div className="usage-totals">{[['今日',usage.today],['累计',usage.total]].map(([label,b])=>{const bucket=b as UsageBucket;return <div key={String(label)}><small>{String(label)}估算{bucket.unknown>0?'（部分）':''}</small><strong>¥{bucket.estimatedYuan.toFixed(6)}</strong><span>{bucket.calls} 次调用{bucket.unknown>0?` · ${bucket.unknown} 次待核算`:''}</span></div>;})}</div><p className="usage-note">从启用费用记录后开始统计，包含已同步的手机用量。豆包官方接口按公开音频费率保守估算；其他模型、缺少用量或失败请求标为待核算。历史调用未补算。</p>{usage.warnings>0 && <p className="notice">有 {usage.warnings} 条记录不完整，统计可能缺失；原记录保留。</p>}{usage.items.length===0?<p className="usage-empty">还没有云端调用记录。</p>:<details className="usage-details"><summary>最近 {usage.items.length} 次调用</summary><div className="usage-table-wrap"><table><thead><tr><th>时间 / 模型</th><th>音频</th><th>输入 / 输出 Token</th><th>估算费用</th></tr></thead><tbody>{usage.items.map(item=><tr key={item.id}><td>{new Date(item.time).toLocaleString('zh-CN')}<small>{item.model}</small><small>{item.file}{item.status==='error'?' · 请求失败':''}</small></td><td>{Number(item.audioSeconds).toFixed(1)} 秒</td><td>{item.inputTokens??'未知'} / {item.outputTokens??'未知'}</td><td>{item.estimatedYuan===null?'待核算':`¥${item.estimatedYuan.toFixed(6)}`}</td></tr>)}</tbody></table></div></details>}</>}</section>}
        {page === 'transcripts' && <div className="archive-filter"><label htmlFor="transcript-day">按日期查看</label><input id="transcript-day" type="date" value={selectedDay} max={localDay()} disabled={loading || !!editing} onChange={event => {const day=event.target.value;if(day)chooseDay(day,day===localDay());}} /><button disabled={loading || !!editing || (followToday && selectedDay===localDay())} onClick={() => chooseDay(localDay(),true)}>今天</button><button disabled={loading || !!editing || selectedDay===''} onClick={() => chooseDay('',false)}>全部历史</button><span>历史字幕自动保留，可按日期查看。</span></div>}
        {page === 'transcripts' && ready && result.items.length === 0 && <div className="empty"><div className="empty-icon">▤</div><h2>{selectedDay ? '这一天还没有字幕' : '还没有字幕'}</h2><p>录音转写并登记后，内容会显示在这里。</p></div>}
        {page === 'transcripts' && ready && result.items.length > 0 && <section className="transcripts"><div className="list-header"><span>字幕内容</span><span>显示第 {offset + 1}–{offset + result.items.length} 条</span></div>{editNotice && !editing && <div className="edit-notice">{editNotice}</div>}{result.items.map(item => <article key={item.id}><time>{item.time || '时间未知'}</time><div className="transcript-body">{editing?.id === item.id ? <div className="editor"><textarea aria-label="修订字幕" maxLength={4000} value={draft} onChange={event => setDraft(event.target.value)} /><div className="editor-actions"><span>保存到修订层，原始字幕保留。</span><button disabled={loading} onClick={() => {setEditing(null);setEditNotice('');}}>取消</button><button className="save-correction" disabled={loading || !draft.trim()} onClick={() => void saveCorrection()}>{loading ? '保存中…' : '保存修订'}</button></div>{editNotice && <p className="edit-error">{editNotice}</p>}</div> : <><p>{item.text}</p><small>{item.source}{item.revision > 0 ? ` · 修订 ${item.revision}` : ''}</small></>}</div>{editing?.id !== item.id && <button className="edit-correction" disabled={loading || !!editing} onClick={() => {setEditing(item);setDraft(item.text);setEditNotice('');}}>修订</button>}</article>)}<div className="pagination"><button disabled={loading || !!editing || offset === 0} onClick={() => void refresh(false, Math.max(0, offset-100), result.snapshot)}>上一页</button><button disabled={loading || !!editing || result.nextOffset === null} onClick={() => void refresh(false, result.nextOffset!, result.snapshot)}>下一页</button></div></section>}
        {page === 'context' && (context?.status === 'ready' || contextOwned) && <div className="context-controls"><div><strong>自动生成</strong><small>{contextOwned ? '运行中 · 每十分钟检查最近字幕' : '本窗口未启动 · 使用已配置的智谱 API'}</small>{notice && <small className="control-notice">{notice}</small>}</div>{contextOwned ? <button className="context-stop" disabled={loading || closing} onClick={() => void stopContext()}>{loading ? '正在停止…' : '停止'}</button> : <button className="context-start" disabled={loading || closing} onClick={() => void startContext()}>{loading ? '正在启动…' : '启动自动生成'}</button>}</div>}
        {page === 'context' && context?.status === 'ready' && !content && <div className="empty"><div className="empty-icon">◷</div><h2>还没有情景</h2><p>{display(context.state.message, '生成情景后，六要素和情节会显示在这里。')}</p></div>}
        {page === 'context' && context?.status === 'ready' && content && <section className="context-card"><div className="context-heading"><strong>情景候选</strong><span>{typeof context.candidate?.createdAt === 'number' && Number.isFinite(context.candidate.createdAt) ? '生成于 ' + new Date(context.candidate.createdAt * 1000).toLocaleString('zh-CN') + ' · ' : ''}{display(context.state.message, '请结合原始字幕核对')}</span></div><div className="element-grid">{elements.map(([key,label]) => <div key={key}><small>{label}</small><p>{display(content.sixElements?.[key]?.value)}</p></div>)}</div><div className="story"><h2>情节</h2><p>{display(content.narrative)}</p></div>{Array.isArray(context.candidate?.sources) && context.candidate.sources.length > 0 && <details><summary>查看来源字幕（{context.candidate.sources.length}）</summary>{context.candidate.sources.map((source,i) => <div className="context-source" key={typeof source?.id === 'string' ? source.id : i}><p>{display(source?.text, '')}</p><small>{display(source?.id, '')}</small></div>)}</details>}</section>}
      </div>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
