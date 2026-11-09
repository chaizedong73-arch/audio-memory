package org.audiomemory.mobile;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.media.*;
import android.os.*;
import org.json.*;
import java.io.*;

public class RecordingService extends Service {
    static volatile boolean active=false,stopping=false;
    static volatile String notice="";
    static volatile long started=0;
    private AudioRecord recorder;
    private PowerManager.WakeLock wake;
    private volatile boolean running=false;
    private Thread capture;
    private Notification notification(String message){
        Intent open=new Intent(this,MainActivity.class);PendingIntent content=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,RecordingService.class).setAction("STOP"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,"recording").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("录音记忆").setContentText(message).setOngoing(true).setContentIntent(content).addAction(new Notification.Action.Builder(null,"停止并保存",stop).build()).build();
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null&&"STOP".equals(intent.getAction())){running=false;stopping=true;notice="正在保存最后一段录音…";return START_NOT_STICKY;}
        if(active||stopping)return START_NOT_STICKY;
        NotificationManager nm=getSystemService(NotificationManager.class);nm.createNotificationChannel(new NotificationChannel("recording","录音状态",NotificationManager.IMPORTANCE_LOW));
        if(Build.VERSION.SDK_INT>=29)startForeground(1,notification("正在录音，音频每30秒保存一段"),ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);else startForeground(1,notification("正在录音，音频每30秒保存一段"));
        running=true;active=true;started=System.currentTimeMillis();notice="";
        wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"audio-memory:recording");wake.acquire(12*60*60*1000L);
        capture=new Thread(this::record,"audio-memory-capture");capture.start();return START_NOT_STICKY;
    }
    private void record(){Store store=new Store(this);File part=null;JSONObject row=null;
        try{
            int buffer=Math.max(4096,AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT));
            recorder=new AudioRecord(MediaRecorder.AudioSource.MIC,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,buffer);
            if(recorder.getState()!=AudioRecord.STATE_INITIALIZED)throw new IOException("麦克风初始化失败");recorder.startRecording();
            byte[] data=new byte[buffer];
            while(running){String id=Store.id();row=new JSONObject().put("id",id).put("deviceId",store.device()).put("startedAt",Store.now()).put("text","").put("model","仅录音").put("transcriptionState",store.config().optBoolean("cloud")?"待转写":"仅录音，未启用云端转写").put("usage",new JSONArray());
                Store.write(store.file(id,".capture"),row);part=store.file(id,".wav.part");int count=0;
                try(FileOutputStream out=new FileOutputStream(part)){out.write(new byte[44]);while(running&&count<30*32000){int n=recorder.read(data,0,Math.min(data.length,30*32000-count));if(n<0)throw new IOException("麦克风读取失败："+n);if(n==0)continue;out.write(data,0,n);count+=n;}out.getFD().sync();}
                if(count>0){finish(store,part,row);Pipeline.enqueue(this,true);SyncJob.schedule(this);}part=null;row=null;
            }
        }catch(Exception e){notice="录音已停止："+e.getClass().getSimpleName()+"；已写音频保留";if(part!=null&&row!=null)try{finish(store,part,row);}catch(Exception ignored){notice="部分录音待恢复；重开软件后检查，原文件保留";}}
        finally{
            running=false;if(recorder!=null){try{recorder.stop();}catch(Exception ignored){}recorder.release();recorder=null;}
            if(wake!=null&&wake.isHeld())wake.release();active=false;stopping=false;
            new Handler(getMainLooper()).post(()->{stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();});
        }
    }
    static void finish(Store store,File part,JSONObject row)throws Exception{
        if(part.length()<=44)return;Wav.finish(part);String id=row.getString("id");File target=store.file(id,".wav");if(!part.renameTo(target))throw new IOException("音频保存失败");
        row.put("sha256",Wav.hash(target)).put("duration",(target.length()-44)/32000.0);store.changed(row);
        // The capture descriptor is only removed after both final files are durable.
        store.file(id,".capture").delete();
    }
    static void recover(Store store){if(active)return;File[] files=store.root.listFiles((dir,name)->name.endsWith(".capture"));if(files==null)return;
        for(File marker:files)try{JSONObject row=Store.read(marker);String id=row.getString("id");File part=store.file(id,".wav.part"),audio=store.file(id,".wav");
            if(part.exists()&&part.length()>44)finish(store,part,row);else if(audio.exists()&&!store.file(id,".json").exists()){row.put("sha256",Wav.hash(audio)).put("duration",(audio.length()-44)/32000.0);store.changed(row);marker.delete();}
        }catch(Exception e){notice="存在未恢复录音，原件已保留。";}
    }
    @Override public void onDestroy(){running=false;super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
