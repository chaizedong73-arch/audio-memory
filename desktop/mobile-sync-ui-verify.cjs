const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
module.exports=async(window,app)=>{
 const run=s=>window.webContents.executeJavaScript(s);
 const wait=async expression=>{for(let i=0;i<900;i++){if(await run(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('timeout '+expression);};
 try{
  await wait("!!document.querySelector('.nav-item')");await run("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('录音')).click()");
  await wait("(()=>{const b=document.querySelector('.mobile-sync-card button');if(!b||b.disabled)return false;b.click();return true;})()");
  await wait("document.querySelector('.mobile-sync-card button').innerText==='关闭接收'");
  const state=await run('window.audioMemory.mobileSyncStatus()');assert.equal(state.status,'ready');
  if(process.env.AUDIO_MEMORY_VERIFY_MOBILE_REMOTE==='1'){
   await run("[...document.querySelectorAll('.mobile-sync-card button')].find(b=>b.innerText==='开启远程同步').click()");
   await wait("!![...document.querySelectorAll('.mobile-sync-card button')].find(b=>b.innerText==='复制远程配对码')");
   const remote=(await run('window.audioMemory.mobileSyncStatus()')).remote;assert.equal(remote.status,'ready');assert.ok(remote.code.startsWith('am1.'));
  }
  await run("document.querySelector('.mobile-sync-card').scrollIntoView({block:'start'})");
  await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  fs.mkdirSync(process.env.AUDIO_MEMORY_VERIFY_OUTPUT,{recursive:true});fs.writeFileSync(path.join(process.env.AUDIO_MEMORY_VERIFY_OUTPUT,process.env.AUDIO_MEMORY_VERIFY_MOBILE_REMOTE==='1'?'desktop-remote-sync.png':'desktop-sync.png'),(await window.webContents.capturePage()).toPNG());
  if(process.env.AUDIO_MEMORY_VERIFY_MOBILE_REMOTE==='1'){
   await run("[...document.querySelectorAll('.mobile-sync-card button')].find(b=>b.innerText==='关闭远程同步').click()");
   await wait("!![...document.querySelectorAll('.mobile-sync-card button')].find(b=>b.innerText==='开启远程同步'&&!b.disabled)");
   assert.equal((await run('window.audioMemory.mobileSyncStatus()')).remote.status,'stopped');
  }
  await run("document.querySelector('.mobile-sync-card button').click()");await wait("document.querySelector('.mobile-sync-card button').innerText==='开启接收'");
  assert.equal((await run('window.audioMemory.mobileSyncStatus()')).status,'stopped');console.log('PASS desktop mobile receiver controls start/stop');app.quit();
 }catch(e){console.error(e);try{console.error(await run('document.body.innerText'));}catch{}app.exit(26);}
};
