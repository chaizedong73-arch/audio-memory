using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Collections.Generic;
using System.Web.Script.Serialization;

namespace AiAudioMemory {
 public sealed class NoteModel{public string id{get;set;}public string label{get;set;}}
 public sealed class NoteSession {
  public string id{get;set;}public string name{get;set;}public string model{get;set;}public string status{get;set;}
  public List<NoteModel> models{get;set;}
  public string Label {get{return name+" · "+model+(status=="working"?" · 运行中":"");}}
 }
 public sealed class NotesSettings {
  public string notesRoot="",description="已有PPT图片骨架时按页补充老师讲授；没有笔记时先梳理知识创建笔记。后续补入或调整PPT时，把既有内容与图片骨架重新衔接。保留手写内容与图片顺序，解释术语，标记重点、AI补充和待核实点。",sessionId="",model="",strategy="auto";
  public bool enabled;public double startedAt;
  public string lesson="";
 }
 public static class AudioControls {
  static readonly Dictionary<string,string> codeRoots=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
  static readonly Dictionary<string,Tuple<DateTime,bool>> classroomCache=new Dictionary<string,Tuple<DateTime,bool>>(StringComparer.OrdinalIgnoreCase);
  public static string DataRoot(string code){
   code=Path.GetFullPath(code);string data=code;
   if(File.Exists(Path.Combine(code,"data_location.py"))){
    string configured=Environment.GetEnvironmentVariable("AUDIO_MEMORY_ROOT");
    data=String.IsNullOrWhiteSpace(configured)?Path.Combine(Path.GetDirectoryName(code),"数据"):Path.GetFullPath(configured);
   }
   lock(codeRoots)codeRoots[data]=code;
   return data;
  }
  public static string CodeRoot(string data){
   if(String.IsNullOrEmpty(data))return data;
   string code;lock(codeRoots)if(codeRoots.TryGetValue(Path.GetFullPath(data),out code))return code;
   return data;
  }
  public static string RootArgument(string data){
   return String.Equals(CodeRoot(data),data,StringComparison.OrdinalIgnoreCase)?"":" --root \""+data+"\"";
  }
  public static bool UsesService(string root){return !String.IsNullOrEmpty(root)&&!String.Equals(CodeRoot(root),root,StringComparison.OrdinalIgnoreCase);}
  public static string Control(string root,string action,object value=null){
   string code=CodeRoot(root),script=Path.Combine(code,"workbench_control.py");
   var info=new ProcessStartInfo(Python(root),"\""+script+"\" --root \""+root+"\" --action "+action){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=code,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
   info.EnvironmentVariables["PYTHONUTF8"]="1";
   using(var process=Process.Start(info)){
    using(var input=new StreamWriter(process.StandardInput.BaseStream,new UTF8Encoding(false))){if(value!=null)input.Write(new JavaScriptSerializer().Serialize(value));}
    string output=process.StandardOutput.ReadToEnd(),error=process.StandardError.ReadToEnd();process.WaitForExit();
    if(process.ExitCode!=0)throw new InvalidOperationException(String.IsNullOrWhiteSpace(error)?"工作台控制失败":error.Trim());return output;
   }
  }
  public static string Python(string root){
   root=CodeRoot(root);
   string bundled=Path.Combine(root,"runtime","python.exe");
   if(File.Exists(bundled))return bundled;
   string portable=Path.Combine(root,".venv","Scripts","python.exe");
   return File.Exists(portable)?portable:Path.Combine(root,"venv","Scripts","python.exe");
  }
  public static string ToolboxRoot(string package){
   string candidate=Path.GetDirectoryName(Path.GetDirectoryName(package));
   return File.Exists(Path.Combine(candidate,"AiWorkbench.Contracts.dll"))?candidate:Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),".tools","ai-agent-monitor");
  }
  public static bool Classroom(string root){
   if(UsesService(root)){
    lock(classroomCache){Tuple<DateTime,bool> cached;if(classroomCache.TryGetValue(root,out cached)&&(DateTime.UtcNow-cached.Item1).TotalMilliseconds<750)return cached.Item2;
     bool result=new JavaScriptSerializer().Deserialize<bool>(Control(root,"classroom-read"));classroomCache[root]=Tuple.Create(DateTime.UtcNow,result);return result;}
   }
   string file=Path.Combine(root,"classroom-mode.json");if(!File.Exists(file))return false;
   object enabled;var state=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file));
   return state!=null&&state.TryGetValue("enabled",out enabled)&&enabled is bool&&(bool)enabled;
  }
  public static void Classroom(string root,bool enabled){
   if(UsesService(root)){Control(root,"classroom-set",new{enabled=enabled});lock(classroomCache)classroomCache.Remove(root);return;}
   Save(Path.Combine(root,"classroom-mode.json"),new {schemaVersion=1,enabled=enabled,generation=Guid.NewGuid().ToString("N"),updatedAt=Now()});
   if(!enabled){var notes=Notes(root);notes.enabled=false;Save(Path.Combine(root,"notes-maintenance.json"),notes);}
  }
  public static NotesSettings Notes(string root){if(UsesService(root))return new JavaScriptSerializer().Deserialize<NotesSettings>(Control(root,"notes-read"))??new NotesSettings();string file=Path.Combine(root,"notes-maintenance.json");return File.Exists(file)?new JavaScriptSerializer().Deserialize<NotesSettings>(File.ReadAllText(file)):new NotesSettings();}
  public static void SaveNotes(string root,NotesSettings settings){if(UsesService(root)){Control(root,"notes-save",settings);return;}Save(Path.Combine(root,"notes-maintenance.json"),settings);}
  public static Dictionary<string,object> SubtitleSettings(string root){if(UsesService(root))return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Control(root,"subtitle-read"));string file=Path.Combine(root,"subtitle-maintenance.json");return File.Exists(file)?new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file)):new Dictionary<string,object>();}
  public static void SaveSubtitleSettings(string root,Dictionary<string,object> settings){if(UsesService(root)){Control(root,"subtitle-save",settings);return;}Save(Path.Combine(root,"subtitle-maintenance.json"),settings);}
  public static Dictionary<string,object> Read(string root){
   if(UsesService(root))return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Control(root,"transcription-read"));
   string file=Path.Combine(root,"transcription-control.json");
   if(!File.Exists(file))return new Dictionary<string,object>();
   return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file))??new Dictionary<string,object>();
  }
  public static string Mode(string root,bool legacyActive){
   var value=Read(root);if(value.Count==0)return legacyActive?"cloud":"local";
   object mode,deadline;
   return value.TryGetValue("mode",out mode)&&Convert.ToString(mode)=="cloud"&&value.TryGetValue("deadline",out deadline)&&Convert.ToDouble(deadline)>Now()?"cloud":"local";
  }
  public static double Now(){return (DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds;}
  public static void Save(string file,object value){
   string temp=file+"."+Guid.NewGuid().ToString("N")+".tmp";
   File.WriteAllText(temp,new JavaScriptSerializer().Serialize(value),new UTF8Encoding(false));
   if(File.Exists(file))File.Replace(temp,file,null);else File.Move(temp,file);
  }
  public static void Switch(string root,string mode){
   if(mode!="local"&&mode!="cloud")throw new ArgumentException("未知转写方式");
   if(!Directory.Exists(root))throw new DirectoryNotFoundException("录音项目未连接");
   if(UsesService(root)){Control(root,"transcription-set",new{mode=mode});return;}
   double now=Now();Save(Path.Combine(root,"transcription-control.json"),new {mode=mode,generation=Guid.NewGuid().ToString("N"),startedAt=now,deadline=now+10800,budgetYuan=5});
  }
 }
}
