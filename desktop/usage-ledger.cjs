const fs=require('node:fs/promises');const path=require('node:path');
async function readUsage(root, now=new Date()) {
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 const result={status:'ready',today:{calls:0,estimatedYuan:0,unknown:0},total:{calls:0,estimatedYuan:0,unknown:0},items:[],warnings:0};
 const rows=[],seen=new Set();
 const add=row=>{if(!row||typeof row.id!=='string'||typeof row.time!=='string'||typeof row.model!=='string'){result.warnings++;return;}if(!seen.has(row.id)){seen.add(row.id);rows.push(row);}};
 const dirs=async folder=>{try{return await fs.readdir(folder,{withFileTypes:true});}catch(e){if(e.code==='ENOENT')return [];throw e;}};
 try {
  const folder=path.join(root,'out','cloud-usage');
  for(const file of (await dirs(folder)).filter(f=>f.isFile()&&/^\d{4}-\d{2}-\d{2}\.jsonl$/.test(f.name))){
   for(const line of (await fs.readFile(path.join(folder,file.name),'utf8')).split(/\r?\n/)){if(!line.trim())continue;try{add(JSON.parse(line));}catch{result.warnings++;}}
  }
  const mobile=path.join(root,'out','mobile-sync');
  for(const device of (await dirs(mobile)).filter(d=>d.isDirectory()&&/^[a-f0-9]{32}$/.test(d.name))){
   const parent=path.join(mobile,device.name);
   for(const recording of (await dirs(parent)).filter(d=>d.isDirectory()&&/^[a-f0-9]{32}$/.test(d.name))){
    try{const meta=JSON.parse(await fs.readFile(path.join(parent,recording.name,'metadata.json'),'utf8'));if(Array.isArray(meta.usage))for(const row of meta.usage)add({...row,device:'mobile'});}catch{result.warnings++;}
   }
  }
  rows.sort((a,b)=>b.time.localeCompare(a.time));
  for(const row of rows){
   const amount=typeof row.estimatedYuan==='number'&&Number.isFinite(row.estimatedYuan)&&row.estimatedYuan>=0?row.estimatedYuan:null;
   for(const b of row.date===today?[result.total,result.today]:[result.total]){b.calls++;if(amount===null)b.unknown++;else b.estimatedYuan+=amount;}
   if(result.items.length<50)result.items.push({...row,estimatedYuan:amount});
  }
  for(const b of [result.today,result.total])b.estimatedYuan=Number(b.estimatedYuan.toFixed(8));return result;
 }catch{return {...result,status:'error',message:'费用记录读取失败，请刷新重试。'};}
}
module.exports={readUsage};
