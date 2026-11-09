package org.audiomemory.mobile;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.net.URL;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

public class MainActivity extends Activity {
    final int ink=Color.rgb(37,42,48),muted=Color.rgb(107,119,124),green=Color.rgb(52,121,103),bg=Color.rgb(247,248,250);
    Store store;LinearLayout outer,body,nav;ScrollView scroll;TextView title,subtitle,recordStatus,timer,feedback,stats,feeToday,feeTotal,feeUnknown;int ticks=0;Button recordButton;String page="录音";Handler handler=new Handler();MediaPlayer player;
    boolean initial=true;
    int dp(float value){return Math.round(value*getResources().getDisplayMetrics().density);}
    GradientDrawable surface(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));if(color==Color.WHITE)d.setStroke(dp(1),Color.rgb(232,236,236));return d;}
    TextView text(String value,int size,int color,boolean bold){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(color);t.setLineSpacing(dp(3),1);if(bold)t.setTypeface(null,Typeface.BOLD);return t;}
    void gap(LinearLayout box,int value){Space s=new Space(this);box.addView(s,new LinearLayout.LayoutParams(1,dp(value)));}
    LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    LinearLayout card(){LinearLayout box=column();box.setPadding(dp(20),dp(20),dp(20),dp(20));box.setBackground(surface(Color.WHITE,16));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(16);body.addView(box,p);return box;}
    Button button(String value,boolean primary,View.OnClickListener action){Button b=new Button(this);b.setText(value);b.setAllCaps(false);b.setTextSize(15);b.setTextColor(primary?Color.WHITE:green);b.setMinHeight(dp(50));b.setPadding(dp(14),dp(8),dp(14),dp(8));b.setBackground(surface(primary?green:Color.rgb(234,244,240),10));b.setOnClickListener(v->{b.animate().scaleX(.98f).scaleY(.98f).setDuration(60).withEndAction(()->b.animate().scaleX(1).scaleY(1).setDuration(100));action.onClick(v);});return b;}
    void notice(String value){if(feedback!=null)feedback.setText(value);Toast.makeText(this,value,Toast.LENGTH_LONG).show();}
    String displayTime(String iso){try{return Instant.parse(iso).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("MM-dd HH:mm:ss"));}catch(Exception e){return iso;}}
    @Override public void onCreate(Bundle state){super.onCreate(state);store=new Store(this);RecordingService.recover(store);if(state!=null)page=state.getString("page","录音");
        outer=column();outer.setBackgroundColor(bg);setContentView(outer);
        if(Build.VERSION.SDK_INT>=30)outer.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets i=insets.getInsets(WindowInsets.Type.systemBars());outer.setPadding(i.left,i.top,i.right,i.bottom);return insets;});
        LinearLayout header=column();header.setPadding(dp(24),dp(20),dp(24),dp(18));title=text("录音记忆",26,ink,true);subtitle=text("记录当下，留给以后查找",14,muted,false);header.addView(title);gap(header,5);header.addView(subtitle);outer.addView(header);
        scroll=new ScrollView(this);scroll.setFillViewport(true);body=column();body.setPadding(dp(20),dp(4),dp(20),dp(24));scroll.addView(body);outer.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        nav=new LinearLayout(this);nav.setPadding(dp(8),dp(8),dp(8),dp(10));nav.setBackgroundColor(Color.WHITE);outer.addView(nav,new LinearLayout.LayoutParams(-1,-2));show(page);
        if(initial){body.setAlpha(0);body.animate().alpha(1).setDuration(180);initial=false;}
        handler.post(tick);SyncJob.schedule(this);Pipeline.enqueue(this,true);
    }
    final Runnable tick=new Runnable(){public void run(){if(page.equals("录音")&&recordStatus!=null){recordStatus.setText(RecordingService.active?(RecordingService.stopping?"正在保存…":"正在录音"):(RecordingService.notice.isEmpty()?"准备开始录音":RecordingService.notice));long seconds=RecordingService.active?(System.currentTimeMillis()-RecordingService.started)/1000:0;timer.setText(String.format(Locale.ROOT,"%02d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60));recordButton.setText(RecordingService.active?"停止并保存":"开始录音");recordButton.setEnabled(!RecordingService.stopping);}if(page.equals("录音")&&ticks++%5==0)updateTotals();if(page.equals("同步")&&feedback!=null)feedback.setText(Pipeline.busy?"正在同步资料…":Pipeline.status);handler.postDelayed(this,1000);}};
    @Override protected void onSaveInstanceState(Bundle out){out.putString("page",page);super.onSaveInstanceState(out);}
    @Override protected void onDestroy(){handler.removeCallbacks(tick);if(player!=null)player.release();super.onDestroy();}
    void show(String next){page=next;body.removeAllViews();recordStatus=null;feedback=null;nav.removeAllViews();
        String[] tabs={"录音","资料","同步","设置"};for(String tab:tabs){Button b=button(tab,false,v->{show(tab);body.setAlpha(.4f);body.animate().alpha(1).setDuration(120);});b.setBackground(surface(tab.equals(page)?Color.rgb(234,244,240):Color.WHITE,8));b.setTextColor(tab.equals(page)?green:muted);nav.addView(b,new LinearLayout.LayoutParams(0,dp(52),1));}
        title.setText(page.equals("录音")?"录音记忆":page.equals("资料")?"我的资料":page.equals("同步")?"同步到电脑":"设置");
        subtitle.setText(page.equals("录音")?"音频先存手机，连上电脑后同步":page.equals("资料")?"原始录音与转写内容一起保留":page.equals("同步")?"远程同步到电脑，手机保留原件":"云端转写与本机保存");
        if(page.equals("录音"))recording();else if(page.equals("资料"))materials();else if(page.equals("同步"))syncPage();else settings();
        scroll.post(()->scroll.scrollTo(0,0));
    }
    void recording(){LinearLayout hero=card();recordStatus=text(RecordingService.active?"正在录音":"准备开始录音",18,green,true);hero.addView(recordStatus);gap(hero,22);timer=text("00:00:00",40,ink,true);timer.setTypeface(Typeface.MONOSPACE);hero.addView(timer);gap(hero,12);hero.addView(text("每 30 秒保存一段，锁屏后继续录音。",14,muted,false));gap(hero,24);
        recordButton=button(RecordingService.active?"停止并保存":"开始录音",true,v->{if(RecordingService.active){startService(new Intent(this,RecordingService.class).setAction("STOP"));return;}if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},40);return;}startRecording();});hero.addView(recordButton,new LinearLayout.LayoutParams(-1,dp(54)));
        LinearLayout connection=card();int total=0,pending=0;for(JSONObject r:store.rows()){total++;if(!r.optBoolean("synced"))pending++;}stats=text(total+" 段录音  ·  "+pending+" 段待同步",16,ink,true);connection.addView(stats);gap(connection,8);connection.addView(text(Pipeline.busy?"正在处理已保存的录音…":"录音停止后也可在“同步”中继续上传。",14,muted,false));
        fees();
    }
    void startRecording(){try{if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},41);startForegroundService(new Intent(this,RecordingService.class));recordStatus.setText("正在连接麦克风…");}catch(Exception e){notice("录音启动失败，请检查麦克风权限。");}}
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results){super.onRequestPermissionsResult(code,permissions,results);if(code==40){if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)startRecording();else notice("未获得麦克风权限，尚未开始录音。");}}
    void fees(){double today=0,total=0;int unknown=0,calls=0;String day=LocalDate.now(ZoneId.of("Asia/Shanghai")).toString();for(JSONObject r:store.rows()){JSONArray list=r.optJSONArray("usage");if(list!=null)for(int i=0;i<list.length();i++){JSONObject u=list.optJSONObject(i);if(u==null)continue;calls++;if(u.isNull("estimatedYuan")){unknown++;continue;}double amount=u.optDouble("estimatedYuan",0);total+=amount;if(u.optString("date").equals(day))today+=amount;}}
        LinearLayout c=card();c.addView(text("云端转写费用",17,ink,true));gap(c,15);feeToday=text(String.format(Locale.ROOT,unknown>0?"今日已知 ¥%.6f":"今日 ¥%.6f",today),24,green,true);c.addView(feeToday);gap(c,6);feeTotal=text(String.format(Locale.ROOT,unknown>0?"累计已知 ¥%.6f  ·  %d 次调用":"累计 ¥%.6f  ·  %d 次调用",total,calls),14,muted,false);c.addView(feeTotal);feeUnknown=text(unknown>0?unknown+" 次待核算，未计入上述金额":"",14,muted,false);c.addView(feeUnknown);gap(c,10);c.addView(text("按返回用量保守估算，实际扣费以服务商账单为准。未返回用量的请求不按零元计算。",13,muted,false));}
    void updateTotals(){if(stats==null||feeToday==null)return;java.util.List<JSONObject> rows=store.rows();int pending=0,unknown=0,calls=0;double today=0,total=0;String day=LocalDate.now(ZoneId.of("Asia/Shanghai")).toString();for(JSONObject r:rows){if(!r.optBoolean("synced"))pending++;JSONArray uses=r.optJSONArray("usage");if(uses==null)continue;for(int i=0;i<uses.length();i++){JSONObject u=uses.optJSONObject(i);if(u==null)continue;calls++;if(u.isNull("estimatedYuan")){unknown++;continue;}double amount=u.optDouble("estimatedYuan",0);total+=amount;if(day.equals(u.optString("date")))today+=amount;}}stats.setText(rows.size()+" 段录音  ·  "+pending+" 段待同步");feeToday.setText(String.format(Locale.ROOT,unknown>0?"今日已知 ¥%.6f":"今日 ¥%.6f",today));feeTotal.setText(String.format(Locale.ROOT,unknown>0?"累计已知 ¥%.6f  ·  %d 次调用":"累计 ¥%.6f  ·  %d 次调用",total,calls));feeUnknown.setText(unknown>0?unknown+" 次待核算，未计入上述金额":"");}
    void materials(){List<JSONObject> rows=store.rows();if(rows.isEmpty()){LinearLayout c=card();c.addView(text("还没有保存的录音",18,ink,true));gap(c,12);c.addView(text("在“录音”页开始记录，完成的音频会显示在这里。",14,muted,false));return;}
        Button refresh=button("刷新资料",false,v->show("资料"));body.addView(refresh);gap(body,16);
        for(JSONObject row:rows){String id=row.optString("id");LinearLayout c=card();c.addView(text(displayTime(row.optString("startedAt"))+"  ·  "+String.format(Locale.ROOT,"%.1f 秒",row.optDouble("duration")),16,ink,true));gap(c,8);c.addView(text(row.optBoolean("synced")?row.optString("syncNote","已同步"):row.optString("syncNote").contains("待重试")?row.optString("syncNote"):"待同步",13,green,false));gap(c,12);String content=row.optString("text");TextView transcript=text(content.isEmpty()?row.optString("transcriptionState","等待转写"):content,16,content.isEmpty()?muted:ink,false);transcript.setTextIsSelectable(true);c.addView(transcript);gap(c,15);
            c.addView(button("播放录音",false,v->{try{if(player!=null)player.release();player=new MediaPlayer();player.setDataSource(store.file(id,".wav").getAbsolutePath());player.prepare();player.start();}catch(Exception e){notice("无法播放录音，原件保留。");}}));gap(c,8);
            c.addView(button(row.optBoolean("attempted")?"重新转写（再次计费）":"转写这段录音",false,v->{((Button)v).setEnabled(false);Pipeline.jobs.execute(()->{try{Pipeline.transcribe(store,id,true);Pipeline.sync(store,id);runOnUiThread(()->{notice("处理结束，费用与资料已更新。");show("资料");});}catch(Exception e){runOnUiThread(()->{notice("处理未完成，原音频保留。");show("资料");});}});}));
            JSONArray usage=row.optJSONArray("usage");if(usage!=null&&usage.length()>0){gap(c,10);for(int i=0;i<usage.length();i++){JSONObject u=usage.optJSONObject(i);if(u!=null)c.addView(text("第 "+(i+1)+" 次 · "+(u.isNull("estimatedYuan")?"费用待核算":String.format(Locale.ROOT,"¥%.6f",u.optDouble("estimatedYuan")))+"\n输入 "+(u.isNull("inputTokens")?"未知":u.optString("inputTokens"))+" / 输出 "+(u.isNull("outputTokens")?"未知":u.optString("outputTokens"))+" Token",14,muted,false));}}
        }
    }
    EditText field(LinearLayout box,String label,String value,boolean secret){box.addView(text(label,14,ink,true));gap(box,5);EditText input=new EditText(this);input.setTextSize(15);input.setSingleLine(true);input.setText(value);input.setPadding(dp(12),dp(9),dp(12),dp(9));input.setBackground(surface(bg,8));if(secret)input.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);box.addView(input,new LinearLayout.LayoutParams(-1,dp(52)));gap(box,15);return input;}
    void syncPage(){JSONObject config;try{config=store.config();}catch(Exception e){notice("配对配置无法读取，请重新配对。");return;}LinearLayout c=card();c.addView(text(config.has("pairing")?"已配对电脑":"连接你的电脑",18,ink,true));gap(c,10);c.addView(text("电脑开启“手机同步接收 → 开启远程同步”，将配对码粘贴到这里。可使用移动数据，不要求同一 Wi-Fi。",14,muted,false));gap(c,18);EditText code=field(c,"电脑配对码","",true);code.setHint("am1.…");
        c.addView(button("验证并保存配对",true,v->{String value=code.getText().toString();((Button)v).setEnabled(false);Pipeline.jobs.execute(()->{try{JSONObject pair=Pipeline.pairing(value);JSONObject r=Pipeline.request(pair.getString("url")+"/v1/sync/health",pair.getString("token"),null,null,Pipeline.syncPin(pair));if(!r.optString("status").equals("ready"))throw new Exception("not ready");JSONObject old=store.config();old.put("pairing",pair);store.config(old);SyncJob.schedule(this);runOnUiThread(()->{notice("配对已保存，可以同步资料。");show("同步");});}catch(Exception e){runOnUiThread(()->{((Button)v).setEnabled(true);notice("配对失败：请检查网络和电脑接收状态，远程通道重开后需使用新配对码。");});}});}));
        gap(c,16);c.addView(button("立即同步全部资料",false,v->{try{if(!store.config().has("pairing")){notice("请先配对电脑。");return;}}catch(Exception e){notice("配对配置无法读取。");return;}Pipeline.enqueue(this,false);SyncJob.schedule(this);notice("已开始同步，原件会保留在手机。");}));gap(c,14);
        long pending=store.rows().stream().filter(r->!r.optBoolean("synced")).count();c.addView(text(pending+" 段待同步",16,ink,true));feedback=text(Pipeline.status,13,muted,false);c.addView(feedback);gap(c,12);c.addView(text("同步仅上传录音、字幕和费用用量，不上传云端服务密钥。连接中断后可再次同步，已保存的资料不会重复生成。远程连接经 Cloudflare 中转，移动数据同步会消耗流量。",13,muted,false));
    }
    void settings(){JSONObject config;try{config=store.config();}catch(Exception e){notice("配置暂时无法解密，原配置保留。");return;}final JSONObject loaded=config;LinearLayout c=card();c.addView(text("转写方式",18,ink,true));gap(c,8);Switch cloud=new Switch(this);cloud.setText("启用云端转写");cloud.setTextSize(15);cloud.setChecked(config.optBoolean("cloud"));c.addView(cloud);gap(c,8);c.addView(text("关闭时只在手机保存录音。开启后，音频会发送到你配置的服务并产生费用。",14,muted,false));gap(c,18);
        c.addView(text("接口协议",14,ink,true));Spinner protocol=new Spinner(this);String[] protocols={"火山方舟音频接口","OpenAI兼容语音转写接口"};protocol.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,protocols));protocol.setSelection(config.optString("protocol","ark_audio").equals("openai_transcription")?1:0);c.addView(protocol,new LinearLayout.LayoutParams(-1,dp(52)));gap(c,12);
        EditText url=field(c,"API 地址",config.optString("url","https://ark.cn-beijing.volces.com/api/v3"),false),model=field(c,"模型名称",config.optString("model","doubao-seed-2-0-mini-260428"),false),key=field(c,"API 密钥","",true);key.setHint(config.optString("key").isEmpty()?"填写服务商密钥":"已保存；留空保持不变");
        c.addView(button("保存设置",true,v->{try{String base=url.getText().toString().trim();for(String suffix:new String[]{"/","/chat/completions","/audio/transcriptions"})if(base.endsWith(suffix))base=base.substring(0,base.length()-suffix.length());URL parsed=new URL(base);if(!parsed.getProtocol().equals("https")||parsed.getUserInfo()!=null||parsed.getQuery()!=null||parsed.getRef()!=null)throw new Exception("请使用HTTPS基础接口地址");String m=model.getText().toString().trim();if(!m.matches("[a-zA-Z0-9._:-]{1,150}"))throw new Exception("模型名称无效");String secret=key.getText().toString().trim();if(secret.isEmpty())secret=loaded.optString("key");if(cloud.isChecked()&&secret.isEmpty())throw new Exception("请填写API密钥");JSONObject current=store.config();current.put("cloud",cloud.isChecked()).put("url",base).put("model",m).put("key",secret).put("protocol",protocol.getSelectedItemPosition()==0?"ark_audio":"openai_transcription");store.config(current);key.setText("");notice("设置已保存，密钥由手机系统加密保护。");Pipeline.enqueue(this,true);}catch(Exception e){notice(e.getMessage()==null?"保存失败，输入保留":e.getMessage());}}));
        gap(c,18);c.addView(text("手机端暂不运行桌面 Whisper 模型。录音和资料存放在应用私有目录；卸载或清除应用数据会移除手机原件，请先同步。",13,muted,false));
    }
}
