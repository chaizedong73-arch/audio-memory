function createClassroomFlow({services, setMode, readMode = async()=>false}) {
  const order=['gateway','visual','context','camera','recording'];
  let active=false, busy=false, enabledHere=false;
  const started=new Set();
  async function start() {
    if(busy)return {status:'busy'};
    if(active)return {status:'active'};
    busy=true;
    try {
      enabledHere=!(await readMode());
      if(enabledHere)await setMode(true);
      active=true;
      const errors=[];
      for(const name of order) {
        const service=services[name];
        if(service.isOwned())continue;
        try {
          const result=await service.start();
          if(result.status==='owned')started.add(name);
          else if(result.status!=='external')errors.push({name,message:result.message || '启动失败'});
        } catch {errors.push({name,message:'启动失败，请查看日志'});}
      }
      return {status:errors.length?'partial':'active',errors};
    } catch {return {status:'error',message:'无法开启课堂模式'};}
    finally {busy=false;}
  }
  async function stop() {
    if(busy)return {status:'busy'};
    if(!active)return {status:'stopped'};
    busy=true;
    try {
      const errors=[];
      for(const name of [...order].reverse()) {
        if(!started.has(name))continue;
        try {
          const result=await services[name].stop();
          if(result.status==='stopped')started.delete(name);
          else errors.push({name,message:result.message || '停止失败'});
        } catch {errors.push({name,message:'停止失败，请查看日志'});}
      }
      if(!errors.length){if(enabledHere)await setMode(false);active=false;enabledHere=false;}
      return {status:errors.length?'partial':'stopped',errors};
    } catch {return {status:'error',message:'关闭课堂模式失败'};}
    finally {busy=false;}
  }
  return {start,stop,isActive:()=>active};
}
module.exports={createClassroomFlow};
