const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
module.exports=async(window,app)=>{
 const run=s=>window.webContents.executeJavaScript(s);
 const wait=async s=>{for(let i=0;i<150;i++){if(await run(s))return;await new Promise(r=>setTimeout(r,100));}throw Error('timeout '+s);};
 try{
  await wait("!!document.querySelector('.nav-item')");
  await run("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('录音')).click()");
  await wait("!!document.querySelector('.usage-totals')");
  const usage=await run('window.audioMemory.readUsage()');assert.equal(usage.status,'ready');
  if(process.env.AUDIO_MEMORY_VERIFY_USAGE_EMPTY==='1'){
   assert.equal(usage.total.calls,0);await wait("document.body.innerText.includes('还没有云端调用记录')");
  }else{
   assert.equal(usage.total.calls,2);assert.equal(usage.total.unknown,1);assert.equal(usage.total.estimatedYuan,0.00069);
   await wait("document.body.innerText.includes('¥0.000690') && document.body.innerText.includes('1 次待核算')");
   await run("document.querySelector('.usage-details').open=true");
  }
  await run("document.querySelector('.usage-card').scrollIntoView({block:'start'})");
  await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  fs.mkdirSync(process.env.AUDIO_MEMORY_VERIFY_OUTPUT,{recursive:true});
  fs.writeFileSync(path.join(process.env.AUDIO_MEMORY_VERIFY_OUTPUT,process.env.AUDIO_MEMORY_VERIFY_USAGE_EMPTY==='1'?'empty-costs.png':'costs.png'),(await window.webContents.capturePage()).toPNG());
  console.log('PASS usage UI '+(usage.total.calls?'estimated and unknown fees retained':'empty ledger'));app.quit();
 }catch(e){console.error(e);app.exit(24);}
};
