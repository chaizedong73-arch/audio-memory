const fs = require('node:fs/promises');
const path = require('node:path');
const gatewayBase = () => 'http://127.0.0.1:' + Number(process.env.AUDIO_MEMORY_TEST_GATEWAY_PORT || 8768);
const empty = status => ({ status, items: [], total: 0, snapshot: '', nextOffset: null });
async function credential(root) {
  try { return (await fs.readFile(path.join(root, 'out', 'ai-gateway', 'access-token'), 'utf8')).trim(); }
  catch { return ''; }
}
async function readTranscripts(root, fetchFn = fetch, options = {}) {
  const token = await credential(root);
  if (!token) return empty('offline');
  const offset = options.offset ?? 0;
  if (!Number.isSafeInteger(offset) || offset < 0 || (options.snapshot && !/^[a-f0-9]{32}$/.test(options.snapshot)) || (options.day && !/^\d{4}-\d{2}-\d{2}$/.test(options.day))) return empty('error');
  const query = new URLSearchParams({kind:'transcript_segment',limit:'100'});
  if (offset) query.set('offset',String(offset));
  if (options.snapshot) query.set('snapshot',options.snapshot);
  if (options.day) query.set('day',options.day);
  try {
    const response = await fetchFn(gatewayBase() + '/v1/materials?' + query, {
      headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(4000)
    });
    if (response.status === 409) return empty('stale');
    if (!response.ok) return empty('error');
    const page = await response.json();
    if (!Array.isArray(page.items) || !Number.isSafeInteger(page.total)) return empty('error');
    return { status:'ready', items:page.items.map(item => ({ id:String(item.id), version:String(item.contentVersion ?? ''), revision:Number(item.data?.effectiveRecord?.revision ?? 0), text:String(item.data?.effectiveRecord?.text ?? item.preview ?? ''), time:String(item.data?.t ?? ''), source:String(item.source ?? '') })), total:page.total, snapshot:typeof page.snapshot === 'string' ? page.snapshot : '', nextOffset:Number.isSafeInteger(page.nextOffset) && page.nextOffset >= 0 ? page.nextOffset : null };
  } catch { return empty('offline'); }
}
async function refreshTranscripts(root, fetchFn = fetch, options = {}) {
  const token = await credential(root);
  if (!token) return empty('offline');
  try {
    const response = await fetchFn(gatewayBase() + '/v1/refresh', { method:'POST', headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(30000) });
    if (!response.ok) return empty('error');
  } catch { return empty('offline'); }
  return readTranscripts(root, fetchFn, options);
}
async function readContext(root, fetchFn = fetch) {
  const token = await credential(root);
  if (!token) return {status:'offline',state:{},candidate:null};
  try {
    const response = await fetchFn(gatewayBase() + '/v1/context/current', {headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(4000)});
    if (!response.ok) return {status:'error',state:{},candidate:null};
    const result = await response.json();
    if (result.schema !== 'context-current/v1' || typeof result.state !== 'object' || result.state === null) return {status:'error',state:{},candidate:null};
    return {status:'ready',state:result.state,candidate:result.candidate && typeof result.candidate === 'object' ? result.candidate : null};
  } catch { return {status:'offline',state:{},candidate:null}; }
}
async function correctTranscript(root, value, fetchFn = fetch) {
  const token = await credential(root);
  if (!token) return {status:'offline',message:'材料网关未连接'};
  if (!value || typeof value.id !== 'string' || typeof value.snapshot !== 'string' || typeof value.contentVersion !== 'string' || typeof value.text !== 'string') return {status:'error',message:'修订内容无效'};
  try {
    const response=await fetchFn(gatewayBase() + '/v1/transcripts/correct',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify(value),signal:AbortSignal.timeout(30000)});
    const body=await response.json();
    if(response.status===409) return {status:'stale',message:'字幕已变化，请先复制草稿，取消编辑后刷新核对'};
    if(!response.ok) return {status:'error',message:typeof body.error==='string' ? body.error : '修订失败'};
    return {status:'ready',changed:!!body.changed,warnings:Array.isArray(body.warnings) ? body.warnings.filter(x=>typeof x==='string') : []};
  } catch { return {status:'offline',message:'无法连接材料网关'}; }
}
async function readVisual(root, fetchFn = fetch) {
  const token = await credential(root);
  if (!token) return {status:'offline',tasks:[]};
  try {
    const response = await fetchFn(gatewayBase() + '/v1/visual/tasks', {headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(4000)});
    if (!response.ok) return {status:'error',tasks:[]};
    const result = await response.json();
    if (result.schema !== 'visual-tasks/v1' || !Array.isArray(result.items)) return {status:'error',tasks:[]};
    return {status:'ready',tasks:result.items};
  } catch { return {status:'offline',tasks:[]}; }
}
module.exports = { readTranscripts, refreshTranscripts, readContext, correctTranscript, readVisual };
