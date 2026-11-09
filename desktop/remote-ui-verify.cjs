const fs=require('node:fs'),path=require('node:path');
module.exports=async(window,app)=>{
 const output=process.env.AUDIO_MEMORY_VERIFY_REMOTE_OUTPUT;fs.mkdirSync(output,{recursive:true});
 const run=source=>window.webContents.executeJavaScript(source);
 const wait=async(source,ms=90000)=>{const end=Date.now()+ms;while(Date.now()<end){if(await run(source))return;await new Promise(resolve=>setTimeout(resolve,150));}throw Error('UI state timeout: '+source);};
 const click=label=>run(`[...document.querySelectorAll('button')].find(x=>x.innerText===${JSON.stringify(label)}&&!x.disabled).click()`);
 const result={};
 try{
  window.webContents.setBackgroundThrottling(false);
  window.setSize(1200,960);
  await wait("!!document.querySelector('.workspace-switch button')");
  await run("[...document.querySelectorAll('.workspace-switch button')].find(x=>x.innerText.includes('上课')).click()");
  await wait("[...document.querySelectorAll('.nav-item')].some(x=>x.innerText.includes('PPT采集'))");
  await run("[...document.querySelectorAll('.nav-item')].find(x=>x.innerText.includes('PPT采集')).click()");
  await wait("[...document.querySelectorAll('button')].some(x=>x.innerText==='启动手机采集'&&!x.disabled)");await click('启动手机采集');
  await wait("[...document.querySelectorAll('button')].some(x=>x.innerText==='远程配对'&&!x.disabled)");
  await click('远程配对');
  await wait("!!document.querySelector('img[alt=\"远程采集二维码\"]')");
  await wait("document.querySelector('img[alt=\"远程采集二维码\"]').complete && document.querySelector('img[alt=\"远程采集二维码\"]').naturalWidth>0");
  result.qrDisplayed=true;
  result.remote=await run("window.audioMemory.cameraStatus().then(x=>({status:x.remote?.status,origin:x.remote?.url?.split('#')[0]}))");
  await wait("[...document.querySelectorAll('button')].some(x=>x.innerText==='关闭远程连接'&&!x.disabled)");
  await run("document.querySelector('img[alt=\"远程采集二维码\"]').scrollIntoView({block:'center'})");
  window.webContents.invalidate();await new Promise(resolve=>setTimeout(resolve,500));
  fs.writeFileSync(path.join(output,'remote-pairing.png'),(await window.webContents.capturePage()).toPNG());
  await click('关闭远程连接');
  await wait("!document.querySelector('img[alt=\"远程采集二维码\"]') && [...document.querySelectorAll('button')].some(x=>x.innerText==='结束采集'&&!x.disabled)");result.remoteRevoked=true;
  await click('结束采集');
  await wait("[...document.querySelectorAll('button')].some(x=>x.innerText==='启动手机采集'&&!x.disabled)");result.cameraStopped=true;
  window.webContents.invalidate();await new Promise(resolve=>setTimeout(resolve,500));
  fs.writeFileSync(path.join(output,'remote-stopped.png'),(await window.webContents.capturePage()).toPNG());result.passed=true;
 }catch(error){result.passed=false;result.error=error.message;fs.writeFileSync(path.join(output,'remote-failed.png'),(await window.webContents.capturePage()).toPNG());}
 finally{fs.writeFileSync(path.join(output,'ui-result.json'),JSON.stringify(result,null,2));app.quit();}
};
