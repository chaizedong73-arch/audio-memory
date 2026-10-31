const fs=require('node:fs/promises');
const path=require('node:path');
async function request(root, endpoint, body) {
  try {
    const runtime=JSON.parse(await fs.readFile(path.join(root,'out','scene','runtime.json'),'utf8'));
    if(typeof runtime.token!=='string' || runtime.port!==19643) return {status:'offline'};
    const response=await fetch('http://127.0.0.1:19643'+endpoint,{
      method:body ? 'POST' : 'GET',headers:{Authorization:'Bearer '+runtime.token,...(body ? {'Content-Type':'application/json'} : {})},
      ...(body ? {body:JSON.stringify(body)} : {}),signal:AbortSignal.timeout(15000)
    });
    const data=await response.json();
    if(!response.ok)return {status:'error',message:typeof data.error==='string' ? data.error : '采集操作失败'};
    return {status:'ready',data};
  } catch { return {status:'offline',message:'手机接收未连接'}; }
}
module.exports={request};
