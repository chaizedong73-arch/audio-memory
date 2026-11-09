const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
module.exports=async(window,app)=>{
 const run=s=>window.webContents.executeJavaScript(s);
 const wait=async s=>{for(let i=0;i<300;i++){if(await run(s))return;await new Promise(r=>setTimeout(r,100));}throw Error('timeout '+s);};
 const output=process.env.AUDIO_MEMORY_VERIFY_OUTPUT;fs.mkdirSync(output,{recursive:true});
 try{
  await wait("!!document.querySelector('.nav-item')");
  await run("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('录音')).click()");
  await wait("!!document.querySelector('.record-start:not(:disabled)')");
  if(process.env.AUDIO_MEMORY_VERIFY_REOPEN==='1'){
   await wait("document.querySelector('select[aria-label=\"音频转写方式\"]').value==='legacy'");
   console.log('PASS persisted cloud choice after reopen');app.quit();return;
  }
  await run("document.querySelector('.record-start').click()");
  await wait("!!document.querySelector('.record-stop:not(:disabled)') && document.body.innerText.includes('正在接收音频')");
  await run("const s=document.querySelector('select[aria-label=\"音频转写方式\"]');if(s.disabled)throw Error('switch disabled while recording');s.value='legacy';s.dispatchEvent(new Event('change',{bubbles:true}))");
  await wait("document.body.innerText.includes('已选择云端转写') && !!document.querySelector('.record-stop:not(:disabled)')");
  fs.writeFileSync(path.join(output,'cloud-switch.png'),(await window.webContents.capturePage()).toPNG());
  await run("document.querySelector('.record-stop').click()");
  await wait("!!document.querySelector('.record-start:not(:disabled)')");
  await run("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('字幕')).click()");
  await run("const content=document.querySelector('.content');const long=document.createElement('section');long.className='transcripts';long.innerHTML=Array.from({length:80},(_,i)=>'<article><time>测试 '+(i+1)+'</time><p>滚动验证用字幕（模拟数据），用于检查左侧导航始终可见。</p></article>').join('');content.append(long)");
  const before=await run("document.querySelector('.sidebar').getBoundingClientRect().top");
  await run("document.querySelector('main').scrollTop=1100");
  const state=await run("({side:document.querySelector('.sidebar').getBoundingClientRect().top,main:document.querySelector('main').scrollTop,body:document.scrollingElement.scrollTop,brand:document.querySelector('.brand').getBoundingClientRect().top})");
  assert.equal(state.side,before);assert.equal(state.main,1100);assert.equal(state.body,0);assert.ok(state.brand>=0);
  fs.writeFileSync(path.join(output,'independent-scroll.png'),(await window.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(output,'layout-result.json'),JSON.stringify(state,null,2));
  console.log('PASS running local → cloud, saved synthetic audio, independent scrolling');app.quit();
 }catch(e){console.error(e);app.exit(23);}
};
