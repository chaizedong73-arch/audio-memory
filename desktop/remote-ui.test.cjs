const fs=require('node:fs/promises'),path=require('node:path'),{spawn}=require('node:child_process');
(async()=>{
 const output=path.resolve(__dirname,'../test-artifacts/2026-11-06-remote/ui');await fs.mkdir(output,{recursive:true});
 await fs.unlink(path.join(output,'ui-result.json')).catch(error=>{if(error.code!=='ENOENT')throw error;});
 const net=require('node:net');const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
 const gatewayProbe=net.createServer();await new Promise(resolve=>gatewayProbe.listen(0,'127.0.0.1',resolve));const gatewayPort=gatewayProbe.address().port;await new Promise(resolve=>gatewayProbe.close(resolve));
 const env={...process.env,AUDIO_MEMORY_TEST_GATEWAY_PORT:String(gatewayPort),AUDIO_MEMORY_TEST_CAMERA_PORT:String(port),AUDIO_MEMORY_VERIFY_REMOTE_OUTPUT:output,AUDIO_MEMORY_TEST_USER_DATA:path.join(output,'appdata'),AUDIO_MEMORY_TEST_REGISTRY:path.join(__dirname,'registry.mjs'),AUDIO_MEMORY_ROOT:path.join(output,'data')};delete env.ELECTRON_RUN_AS_NODE;
 const child=spawn(path.join(__dirname,'node_modules/electron/dist/electron.exe'),['.'],{cwd:__dirname,env,windowsHide:true,stdio:'ignore'});
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});
 const result=JSON.parse(await fs.readFile(path.join(output,'ui-result.json'),'utf8'));if(code!==0||!result.passed)throw Error(JSON.stringify(result));
 const records=JSON.parse(await fs.readFile(path.join(output,'appdata/process-registry/process-registry.json'),'utf8')).processes;
 if(!records.some(x=>x.name?.startsWith('Scene-Remote-'))||records.some(x=>x.status==='running'))throw Error('Service cleanup was not verified');
 console.log('PASS: actual Electron controls create a real tunnel QR, revoke it, stop camera and unregister all owned services');
})().catch(error=>{console.error(error.message);process.exitCode=1;});
