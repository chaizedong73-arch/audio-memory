package org.audiomemory.mobile;
import android.app.job.*;
import android.content.*;
import org.json.JSONObject;
public class SyncJob extends JobService {
    static void schedule(Context c){JobScheduler scheduler=c.getSystemService(JobScheduler.class);int network=JobInfo.NETWORK_TYPE_UNMETERED;try{if(new Store(c).config().optJSONObject("pairing")!=null&&new Store(c).config().getJSONObject("pairing").optString("transport").equals("remote"))network=JobInfo.NETWORK_TYPE_ANY;}catch(Exception ignored){}scheduler.schedule(new JobInfo.Builder(79,new ComponentName(c,SyncJob.class)).setRequiredNetworkType(network).setMinimumLatency(3000).setBackoffCriteria(30000,JobInfo.BACKOFF_POLICY_EXPONENTIAL).build());}
    @Override public boolean onStartJob(JobParameters p){Pipeline.jobs.execute(()->{boolean retry=false;try{Store s=new Store(this);if(s.config().has("pairing"))for(JSONObject row:s.rows())try{if(!Pipeline.sync(s,row.getString("id")))retry=true;}catch(Exception e){retry=true;}}catch(Exception e){retry=true;}jobFinished(p,retry);});return true;}
    @Override public boolean onStopJob(JobParameters p){return true;}
}
