const fs=require('node:fs/promises');
const path=require('node:path');
async function request(root, endpoint, body) {
  try {
    const runtime=JSON.parse(await fs.readFile(path.join(root,'out','scene','runtime.json'),'utf8'));
    const port=Number(process.env.AUDIO_MEMORY_TEST_CAMERA_PORT || 19643);
    if(typeof runtime.token!=='string' || runtime.port!==port) return {status:'offline'};
    const response=await fetch('http://127.0.0.1:'+port+endpoint,{
      method:body ? 'POST' : 'GET',headers:{Authorization:'Bearer '+runtime.token,...(body ? {'Content-Type':'application/json'} : {})},
      ...(body ? {body:JSON.stringify(body)} : {}),signal:AbortSignal.timeout(endpoint==='/remote' ? 90000 : 15000)
    });
    const data=await response.json();
    if(!response.ok)return {status:'error',message:typeof data.error==='string' ? data.error : '采集操作失败'};
    return {status:'ready',data};
  } catch { return {status:'offline',message:'手机接收未连接'}; }
}
module.exports={request};
