const fs=require('node:fs/promises');const path=require('node:path');const https=require('node:https');const crypto=require('node:crypto');
async function remoteCommand(root,stop=false){
 try{
  const folder=path.join(root,'config/mobile-sync');
  const [ca,token]=await Promise.all([fs.readFile(path.join(folder,'server.pem')),fs.readFile(path.join(folder,'access-token'),'utf8')]);
  const expected=new crypto.X509Certificate(ca).fingerprint256;
  return await new Promise(resolve=>{
   const req=https.request({hostname:'127.0.0.1',port:Number(process.env.AUDIO_MEMORY_TEST_SYNC_PORT||8769),path:stop?'/v1/sync/remote/stop':'/v1/sync/remote',method:'POST',ca,
    checkServerIdentity:(_host,cert)=>cert.fingerprint256===expected?undefined:new Error('receiver certificate changed'),
    headers:{Authorization:'Bearer '+token.trim(),'Content-Length':'0'},timeout:90000},response=>{
     let text='';response.setEncoding('utf8');response.on('data',part=>{text+=part;if(text.length>16384)req.destroy();});
     response.on('end',()=>{try{const value=JSON.parse(text);resolve(response.statusCode===200?value:{status:'error',message:value.message||'远程连接失败，请重试。'});}catch{resolve({status:'error',message:'接收服务返回无效响应。'});}});
    });
   req.on('timeout',()=>req.destroy());req.on('error',()=>resolve({status:'error',message:'无法连接手机接收服务，请重新开启接收。'}));req.end();
  });
 }catch{return {status:'error',message:'请先开启手机同步接收。'};}
}
module.exports={remoteCommand};
