using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace AiAudioMemory {
 public sealed class TextRange {
  public int DisplayStart,DisplayLength,Revision;public string Id,Source,File,Original,Text;public double Start,End;
 }
 public sealed class CorrectionRecord {
  public string id,sourceFile,file,original,text;public double start,end;public int revision;
 }
 public sealed class CorrectionNote {
  public string id,recordId,selected,instruction,replacement,status,batchId,error,createdAt,appliedAt;public int selectionStartUtf16,selectionLengthUtf16,baseRevision;public object evidence;
  [ScriptIgnore] public string Label {get{return (status=="draft"?"待提交":status=="submitted"?"修订中":status=="applied"?"已修订":status=="needs_review"?"需核对":"失败")+"  「"+selected+"」\n"+instruction+(String.IsNullOrEmpty(replacement)?"":"\n改为："+replacement)+(String.IsNullOrEmpty(error)?"":"\n"+error);}}
 }
 public sealed class CorrectionState {
  public int schemaVersion=1;public Dictionary<string,CorrectionRecord> records=new Dictionary<string,CorrectionRecord>();public List<CorrectionNote> annotations=new List<CorrectionNote>();
 }
 public static class Corrections {
  static JavaScriptSerializer Json {get{return new JavaScriptSerializer{MaxJsonLength=16*1024*1024};}}
  static bool UseService(string root){return !String.Equals(AudioControls.CodeRoot(root),root,StringComparison.OrdinalIgnoreCase);}
  static string Call(string root,string action,object value){
   string code=AudioControls.CodeRoot(root),python=AudioControls.Python(root),script=Path.Combine(code,"transcript_corrections.py");
   var info=new ProcessStartInfo(python,"\""+script+"\" --root \""+root+"\" --annotation-action "+action){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=code,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
   info.EnvironmentVariables["PYTHONUTF8"]="1";
   using(var process=Process.Start(info)){
    using(var input=new StreamWriter(process.StandardInput.BaseStream,new UTF8Encoding(false))){if(value!=null)input.Write(Json.Serialize(value));}
    string output=process.StandardOutput.ReadToEnd(),error=process.StandardError.ReadToEnd();process.WaitForExit();
    if(process.ExitCode!=0)throw new InvalidOperationException(String.IsNullOrWhiteSpace(error)?"批注服务失败":error.Trim());
    return output;
   }
  }
  public static string Normalize(string value){return (value??"").Replace("\r\n","\n").Replace("\r","\n");}
  public static string Key(string source,string file,double start,double end){
   string raw=Path.GetFullPath(source).Replace('/','\\').ToLowerInvariant()+"\n"+file+"\n"+start.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)+"\n"+end.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture);
   using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(raw))).Replace("-","").ToLowerInvariant();
  }
  public static CorrectionState Read(string root){
   if(UseService(root))return Json.Deserialize<CorrectionState>(Call(root,"read",null))??new CorrectionState();
   string path=Path.Combine(root,"transcript-corrections.json");if(!File.Exists(path))return new CorrectionState();
   return Json.Deserialize<CorrectionState>(AudioPane.Tail(path,16*1024*1024,false))??new CorrectionState();
  }
  static string MaterialSuffix(string path){
   if(String.IsNullOrEmpty(path))return "";
   string[] parts=path.Replace('\\','/').Split('/');int found=-1;
   for(int i=0;i<parts.Length;i++)if(parts[i].Equals("out",StringComparison.OrdinalIgnoreCase))found=i;
   return found<0?"":String.Join("/",parts,found+1,parts.Length-found-1);
  }
  public static string FindRecord(CorrectionState state,string source,string file,double start,double end,string original){
   string key=Key(source,file,start,end);if(state.records.ContainsKey(key))return key;
   string suffix=MaterialSuffix(source),match=null;if(suffix.Length==0)return key;
   foreach(var pair in state.records){var record=pair.Value;
    if(record!=null&&String.Equals(MaterialSuffix(record.sourceFile),suffix,StringComparison.OrdinalIgnoreCase)&&record.file==file&&record.start==start&&record.end==end&&Normalize(record.original)==Normalize(original)){
     if(match!=null)throw new InvalidOperationException("历史修订有多条匹配，请人工核对");match=pair.Key;
    }
   }
   return match??key;
  }
  static FileStream Lock(string root){
   var until=DateTime.UtcNow.AddSeconds(3);
   do{try{return new FileStream(Path.Combine(root,".transcript-corrections.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);}catch(IOException){Thread.Sleep(30);}}while(DateTime.UtcNow<until);
   throw new IOException("修订记录正在使用，请稍后重试");
  }
  static void Save(string root,CorrectionState state){
   string path=Path.Combine(root,"transcript-corrections.json"),temp=path+".tmp";
   File.WriteAllText(temp,Json.Serialize(state),new UTF8Encoding(false));
   if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);
  }
  public static CorrectionNote Add(string root,TextRange range,int start,int length,string instruction,string replacement){
   if(start<0||length<1||start+length>range.Text.Length||String.IsNullOrWhiteSpace(instruction))throw new ArgumentException("请选择文字并填写修改意见");
   if(UseService(root))return Json.Deserialize<CorrectionNote>(Call(root,"add",new {source=range.Source,recordId=range.Id,original=range.Original,text=range.Text,revision=range.Revision,selectionStartUtf16=start,selectionLengthUtf16=length,instruction=instruction,replacement=replacement}));
   using(Lock(root)){
    var state=Read(root);CorrectionRecord record;
    if(state.records.TryGetValue(range.Id,out record)){
     if(record.revision!=range.Revision||record.text!=range.Text)throw new InvalidOperationException("正文已有新修订，请重新选择文字");
    }else{record=new CorrectionRecord{id=range.Id,sourceFile=range.Source,file=range.File,start=range.Start,end=range.End,original=range.Original,text=range.Text,revision=0};state.records.Add(record.id,record);}
    var note=new CorrectionNote{id=Guid.NewGuid().ToString("N"),recordId=record.id,selected=range.Text.Substring(start,length),selectionStartUtf16=start,selectionLengthUtf16=length,instruction=instruction.Trim(),replacement=replacement==null?"":Normalize(replacement),baseRevision=record.revision,status="draft",createdAt=DateTime.Now.ToString("o")};
    state.annotations.Add(note);Save(root,state);return note;
   }
  }
  public static string Submit(string root){
   if(UseService(root))return Json.Deserialize<string>(Call(root,"submit",new {}));
   using(Lock(root)){
    var state=Read(root);if(state.annotations.Exists(n=>n.status=="submitted"))throw new InvalidOperationException("上一批仍在修订，请稍后再提交");
    var notes=state.annotations.FindAll(n=>n.status=="draft"||n.status=="failed");if(notes.Count==0)throw new InvalidOperationException("暂无待提交批注");
    string batch=Guid.NewGuid().ToString("N");foreach(var note in notes){note.status="submitted";note.batchId=batch;note.error="";}Save(root,state);return batch;
   }
  }
  public static void Remove(string root,string id){if(UseService(root)){Call(root,"remove",new{id=id});return;}using(Lock(root)){var state=Read(root);var note=state.annotations.Find(n=>n.id==id);if(note!=null&&note.status!="submitted"&&note.status!="applied"){state.annotations.Remove(note);Save(root,state);}}}
  public static void FailBatch(string root,string batch,string error){if(UseService(root)){Call(root,"fail",new{batch=batch,error=error});return;}using(Lock(root)){var state=Read(root);foreach(var note in state.annotations)if(note.batchId==batch&&note.status=="submitted"){note.status="failed";note.error=error;}Save(root,state);}}
  public static void Edit(string root,string id,string instruction,string replacement){if(UseService(root)){Call(root,"edit",new{id=id,instruction=instruction,replacement=replacement});return;}using(Lock(root)){var state=Read(root);var note=state.annotations.Find(n=>n.id==id);if(note==null||note.status=="applied"||note.status=="submitted")throw new InvalidOperationException("这条批注不能再编辑");note.instruction=instruction;note.replacement=Normalize(replacement);note.status="draft";note.error="";Save(root,state);}}
 }
}
