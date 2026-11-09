package org.audiomemory.mobile;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import org.json.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;
import java.time.Instant;
import java.util.*;

final class Store {
    final File root;
    private final Context context;
    static final Object LOCK=new Object();
    Store(Context c){context=c.getApplicationContext();root=new File(context.getFilesDir(),"recordings");root.mkdirs();}
    static String id(){return UUID.randomUUID().toString().replace("-","");}
    static String now(){return Instant.now().toString();}
    String device(){android.content.SharedPreferences p=context.getSharedPreferences("identity",0);String value=p.getString("device",null);if(value==null){value=id();p.edit().putString("device",value).commit();}return value;}
    File file(String id,String extension){if(!id.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("无效录音编号");return new File(root,id+extension);}
    static JSONObject read(File f)throws Exception{return new JSONObject(new String(Files.readAllBytes(f.toPath()),StandardCharsets.UTF_8));}
    static void write(File target,JSONObject value)throws Exception{
        AtomicFile atomic=new AtomicFile(target);FileOutputStream output=null;
        try{output=atomic.startWrite();output.write(value.toString().getBytes(StandardCharsets.UTF_8));atomic.finishWrite(output);}catch(Exception e){if(output!=null)atomic.failWrite(output);throw e;}
    }
    void save(JSONObject row)throws Exception{synchronized(LOCK){write(file(row.getString("id"),".json"),row);}}
    JSONObject load(String id)throws Exception{synchronized(LOCK){return read(file(id,".json"));}}
    List<JSONObject> rows(){synchronized(LOCK){List<JSONObject> values=new ArrayList<>();File[] files=root.listFiles((dir,name)->name.matches("[a-f0-9]{32}\\.json"));if(files!=null)for(File f:files)try{values.add(read(f));}catch(Exception e){RecordingService.notice="有记录暂时无法读取，原文件保留。";}values.sort((a,b)->b.optString("startedAt").compareTo(a.optString("startedAt")));return values;}}
    private javax.crypto.SecretKey secret()throws Exception{
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);String alias="audio-memory-settings-v1";
        if(!ks.containsAlias(alias)){KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");gen.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());gen.generateKey();}
        return ((KeyStore.SecretKeyEntry)ks.getEntry(alias,null)).getSecretKey();
    }
    JSONObject config()throws Exception{
        String saved=context.getSharedPreferences("private-settings",0).getString("encrypted",null);if(saved==null)return new JSONObject();
        JSONObject wrapper=new JSONObject(saved);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,secret(),new GCMParameterSpec(128,Base64.decode(wrapper.getString("iv"),Base64.NO_WRAP)));
        return new JSONObject(new String(c.doFinal(Base64.decode(wrapper.getString("data"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
    }
    void config(JSONObject value)throws Exception{Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,secret());JSONObject data=new JSONObject().put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP)).put("data",Base64.encodeToString(c.doFinal(value.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));if(!context.getSharedPreferences("private-settings",0).edit().putString("encrypted",data.toString()).commit())throw new IOException("配置保存失败");}
    void changed(JSONObject row)throws Exception{row.put("updatedAt",now());row.put("synced",false);save(row);}
}
