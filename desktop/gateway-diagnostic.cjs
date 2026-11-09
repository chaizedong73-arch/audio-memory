const {app}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const {createServiceController}=require('./service-controller.cjs');
app.setPath('userData',path.resolve(__dirname,'../test-artifacts/gateway-diagnostic/user-data'));
app.whenReady().then(async()=>{
 const root=path.resolve(__dirname,'..');
 const c=createServiceController({root,projectRoot:root,nodeExecutable:process.execPath,registryPath:path.join(__dirname,'registry.mjs'),registryDir:path.join(root,'test-artifacts/gateway-diagnostic/registry')});
 const started=Date.now(),result={};
 try{result.start=await c.start();result.elapsedMs=Date.now()-started;const page=await require('./gateway-client.cjs').readTranscripts(root);result.read={status:page.status,total:page.total};}
 finally{result.stop=await c.stop();fs.writeFileSync(path.join(root,'test-artifacts/gateway-diagnostic/result.json'),JSON.stringify(result,null,2));app.quit();}
});
