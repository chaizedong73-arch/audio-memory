package org.audiomemory.mobile;
import android.app.*;
import android.content.*;
import android.os.*;
import android.graphics.Bitmap;
import android.view.*;
import android.widget.Button;
import org.json.*;
import java.io.*;

/** Installed only by build.py --test, never in the deliverable APK. */
public class MobileChecks extends Instrumentation {
    Bundle args;
    @Override public void onCreate(Bundle input){args=input;start();}
    void checkPendingReceipt()throws Exception{
        JSONObject sent=new JSONObject().put("updatedAt","v1"), current=new JSONObject().put("updatedAt","v1");
        check(Pipeline.applySyncReceipt(current,sent,new JSONObject().put("indexPending",true)),"pending receipt ignored");
        check(!current.getBoolean("synced")&&current.getString("syncNote").contains("待重试"),"pending index marked synced");
        check(Pipeline.applySyncReceipt(current,sent,new JSONObject().put("indexPending",false).put("gatewayRefreshed",true)),"completed receipt ignored");
        check(current.getBoolean("synced"),"completed index not marked synced");
        current.put("updatedAt","v2");check(!Pipeline.applySyncReceipt(current,sent,new JSONObject()),"stale receipt overwrote new revision");
    }
    void checkSyncRetryFlow()throws Exception{
        Store store=new Store(getTargetContext());String id=Store.id(), stamp=Store.now();
        JSONObject row=new JSONObject().put("id",id).put("deviceId",store.device()).put("startedAt",stamp).put("updatedAt",stamp).put("synced",false);
        store.save(row);try(FileOutputStream audio=new FileOutputStream(store.file(id,".wav"))){audio.write(new byte[]{1,2,3});}
        store.config(new JSONObject().put("pairing",new JSONObject()));
        boolean first=Pipeline.sync(store,id,(pair,bytes)->new JSONObject().put("status","saved").put("id",id).put("indexPending",true));
        check(!first&&!store.load(id).getBoolean("synced"),"pending package did not request retry");
        boolean second=Pipeline.sync(store,id,(pair,bytes)->new JSONObject().put("status","saved").put("id",id).put("indexPending",false).put("gatewayRefreshed",true));
        check(second&&store.load(id).getBoolean("synced"),"retry did not complete");
    }
    void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    void waitFor(java.util.concurrent.Callable<Boolean> condition)throws Exception{long until=SystemClock.elapsedRealtime()+15000;while(SystemClock.elapsedRealtime()<until){if(condition.call())return;SystemClock.sleep(100);}throw new AssertionError("condition timed out");}
    View find(View view,String text){if(view instanceof Button&&((Button)view).getText().toString().equals(text))return view;if(view instanceof android.view.ViewGroup){android.view.ViewGroup group=(android.view.ViewGroup)view;for(int i=0;i<group.getChildCount();i++){View found=find(group.getChildAt(i),text);if(found!=null)return found;}}return null;}
    void screenshot(String name)throws Exception{getUiAutomation().waitForIdle(300,5000);Bitmap image=getUiAutomation().takeScreenshot();check(image!=null,"screenshot missing");for(int i=0;i<20;i++){SystemClock.sleep(100);Bitmap next=getUiAutomation().takeScreenshot();boolean stable=next!=null&&image.sameAs(next);if(next!=null)image=next;if(stable)break;}try(FileOutputStream out=new FileOutputStream(new File(getTargetContext().getFilesDir(),name+".png"))){image.compress(Bitmap.CompressFormat.PNG,100,out);}}
    @Override public void onStart(){Bundle result=new Bundle();try{checkPendingReceipt();if("true".equals(args.getString("receiptOnly"))){checkSyncRetryFlow();result.putString("result","PASS receipt retry and revision checks");finish(Activity.RESULT_OK,result);return;}
        MainActivity activity=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));waitForIdleSync();
        Store store=new Store(activity);check(store.rows().isEmpty(),"fixture must be empty");screenshot("01-empty");
        runOnMainSync(()->{View v=find(activity.getWindow().getDecorView(),"开始录音");check(v!=null,"record button");v.performClick();});
        waitFor(()->RecordingService.active);getUiAutomation().executeShellCommand("input keyevent 223").close();
        SystemClock.sleep(2500);check(RecordingService.active,"recording stopped when screen off");
        runOnMainSync(()->activity.startService(new Intent(activity,RecordingService.class).setAction("STOP")));
        waitFor(()->!RecordingService.active&&!store.rows().isEmpty());JSONObject recorded=store.rows().get(0);check(store.file(recorded.getString("id"),".wav").length()>44,"audio not saved");
        getUiAutomation().executeShellCommand("input keyevent 224").close();getUiAutomation().executeShellCommand("wm dismiss-keyguard").close();
        activity.getSystemService(android.app.job.JobScheduler.class).cancelAll();Pipeline.jobs.submit(()->{}).get();
        JSONObject config=store.config();JSONObject pair=new JSONObject(args.getString("pairing"));
        // The PC test runner provides a fixture-only token and certificate, never user credentials.
        config.put("pairing",pair);config.put("cloud",false);store.config(config);
        JSONObject restored=new Store(activity).config();check(restored.getJSONObject("pairing").getString("token").equals(pair.getString("token")),"pairing did not survive readback");
        JSONObject denied=new JSONObject(pair.toString()).put("fingerprint",new String(new char[64]).replace('\0','0'));
        boolean rejected=false;try{Pipeline.request(denied.getString("url")+"/v1/sync/health",denied.getString("token"),null,null,denied.getString("fingerprint"));}catch(Exception e){rejected=true;}check(rejected,"certificate mismatch accepted");
        String id=Store.id();File raw=store.file(id,".wav");try(FileOutputStream out=new FileOutputStream(raw)){out.write(new byte[44]);byte[] pcm=new byte[32000];for(int i=0;i<pcm.length;i+=2)pcm[i]=1;out.write(pcm);}Wav.finish(raw);
        JSONObject item=new JSONObject().put("id",id).put("deviceId",store.device()).put("startedAt",Store.now()).put("text","安卓同步验收：明天九点讨论课堂资料").put("model","synthetic-test").put("sha256",Wav.hash(raw)).put("duration",1).put("usage",new JSONArray());store.changed(item);
        // Trust only the isolated fixture certificate for cloud protocol tests; release code never sets global trust.
        javax.net.ssl.SSLSocketFactory previous=javax.net.ssl.HttpsURLConnection.getDefaultSSLSocketFactory();javax.net.ssl.HostnameVerifier previousHost=javax.net.ssl.HttpsURLConnection.getDefaultHostnameVerifier();
        javax.net.ssl.SSLContext fixtureTls=javax.net.ssl.SSLContext.getInstance("TLS");
        final String expectedPin=pair.getString("fingerprint");
        fixtureTls.init(null,new javax.net.ssl.TrustManager[]{new javax.net.ssl.X509TrustManager(){public java.security.cert.X509Certificate[]getAcceptedIssuers(){return new java.security.cert.X509Certificate[0];}public void checkClientTrusted(java.security.cert.X509Certificate[] c,String a){}public void checkServerTrusted(java.security.cert.X509Certificate[] chain,String a)throws java.security.cert.CertificateException{try{check(Wav.hex(java.security.MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded())).equals(expectedPin),"wrong fixture certificate");}catch(Exception e){throw new java.security.cert.CertificateException(e);}}}},null);
        javax.net.ssl.HttpsURLConnection.setDefaultSSLSocketFactory(fixtureTls.getSocketFactory());javax.net.ssl.HttpsURLConnection.setDefaultHostnameVerifier((h,session)->h.equals("10.0.2.2"));
        try{
            JSONObject cloud=store.config().put("cloud",true).put("url",pair.getString("url")).put("model","fixture-model").put("key",pair.getString("token")).put("protocol","ark_audio");store.config(cloud);
            Pipeline.transcribe(store,id,false);check(store.load(id).getString("text").equals("原生云端请求协议验收"),"cloud response not stored");
            Pipeline.transcribe(store,id,false);check(store.load(id).getJSONArray("usage").length()==1,"automatic duplicate request");
            cloud.put("url",pair.getString("url")+"/fail");store.config(cloud);Pipeline.transcribe(store,id,true);check(store.load(id).getJSONArray("usage").length()==2,"failed attempt not recorded");check(store.load(id).getString("text").equals("原生云端请求协议验收"),"failed retry destroyed transcript");
            cloud.put("url",pair.getString("url")).put("protocol","openai_transcription");store.config(cloud);Pipeline.transcribe(store,id,true);check(store.load(id).getString("text").equals("兼容语音转写接口验收"),"multipart response not stored");
            JSONObject price=Pipeline.usage(new JSONObject().put("usage",new JSONObject().put("prompt_tokens",107).put("completion_tokens",12)),new JSONObject().put("url","https://ark.cn-beijing.volces.com/api/v3").put("model","doubao-seed-2-0-mini-260428"),store.load(id),null);check(Math.abs(price.getDouble("estimatedYuan")-0.000690)<0.00000001,"native rate formula");
            store.config(store.config().put("cloud",false));
        }finally{javax.net.ssl.HttpsURLConnection.setDefaultSSLSocketFactory(previous);javax.net.ssl.HttpsURLConnection.setDefaultHostnameVerifier(previousHost);}
        Pipeline.sync(store,id);check(store.load(id).optBoolean("synced"),"sync not acknowledged");
        JSONObject synced=store.load(id);synced.put("synced",false);store.save(synced);Pipeline.sync(store,id);check(store.load(id).optBoolean("synced"),"repeat sync failed");
        JSONObject update=store.load(id);update.put("text","安卓同步验收：修订后仍然可以追溯音频");store.changed(update);Pipeline.sync(store,id);
        String remoteCode=args.getString("remotePairing");
        if(remoteCode!=null){
            JSONObject remote=Pipeline.pairing(remoteCode);check(Pipeline.syncPin(remote)==null,"remote must use system HTTPS trust");
            JSONObject remoteConfig=store.config().put("pairing",remote);store.config(remoteConfig);
            JSONObject ready=Pipeline.request(remote.getString("url")+"/v1/sync/health",remote.getString("token"),null,null,null);check(ready.optString("status").equals("ready"),"public health failed");
            JSONObject pending=store.load(id);store.changed(pending);Pipeline.sync(store,id);check(store.load(id).optBoolean("synced"),"native public upload not acknowledged");
            boolean deniedRemote=false;try{Pipeline.request(remote.getString("url")+"/v1/materials",remote.getString("token"),null,null,null);}catch(Exception e){deniedRemote=true;}check(deniedRemote,"remote exposed material gateway");
            check(new Store(activity).config().getJSONObject("pairing").getString("transport").equals("remote"),"remote pairing not persisted");
        }
        for(String tab:new String[]{"录音","资料","同步","设置"}){runOnMainSync(()->activity.show(tab));waitForIdleSync();screenshot("02-"+tab);}
        result.putString("result","PASS native recording while screen off, durable WAV, encrypted settings readback, pin rejection, HTTPS sync, idempotent retry and transcript update");result.putString("mobileId",id);finish(Activity.RESULT_OK,result);
    }catch(Throwable error){result.putString("error",android.util.Log.getStackTraceString(error));finish(Activity.RESULT_CANCELED,result);}}
}
