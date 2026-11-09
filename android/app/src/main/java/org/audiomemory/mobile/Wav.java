package org.audiomemory.mobile;
import java.io.*;
import java.security.MessageDigest;
final class Wav {
    static void le(RandomAccessFile f,long n,int bytes)throws IOException{for(int i=0;i<bytes;i++)f.write((int)(n>>(i*8))&255);}
    static void finish(File file)throws Exception{
        try(RandomAccessFile f=new RandomAccessFile(file,"rw")){long count=Math.max(0,f.length()-44);count-=count%2;f.setLength(count+44);f.seek(0);f.writeBytes("RIFF");le(f,count+36,4);f.writeBytes("WAVEfmt ");le(f,16,4);le(f,1,2);le(f,1,2);le(f,16000,4);le(f,32000,4);le(f,2,2);le(f,16,2);f.writeBytes("data");le(f,count,4);f.getFD().sync();}
    }
    static boolean silent(File file)throws Exception{try(InputStream in=new FileInputStream(file)){long skipped=in.skip(44);if(skipped!=44)return false;byte[] data=new byte[8192];int n;while((n=in.read(data))!=-1)for(int i=0;i<n;i++)if(data[i]!=0)return false;return true;}}
    static String hash(File file)throws Exception{MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)digest.update(b,0,n);}return hex(digest.digest());}
    static String hex(byte[] bytes){StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();}
}
