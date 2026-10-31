using System;
using System.IO;
using System.Text;
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
  public static string Python(string root){
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
   string file=Path.Combine(root,"classroom-mode.json");if(!File.Exists(file))return false;
   object enabled;var state=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file));
   return state!=null&&state.TryGetValue("enabled",out enabled)&&enabled is bool&&(bool)enabled;
  }
  public static void Classroom(string root,bool enabled){
   Save(Path.Combine(root,"classroom-mode.json"),new {schemaVersion=1,enabled=enabled,generation=Guid.NewGuid().ToString("N"),updatedAt=Now()});
   if(!enabled){var notes=Notes(root);notes.enabled=false;Save(Path.Combine(root,"notes-maintenance.json"),notes);}
  }
  public static NotesSettings Notes(string root){string file=Path.Combine(root,"notes-maintenance.json");return File.Exists(file)?new JavaScriptSerializer().Deserialize<NotesSettings>(File.ReadAllText(file)):new NotesSettings();}
  public static Dictionary<string,object> Read(string root){
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
   double now=Now();Save(Path.Combine(root,"transcription-control.json"),new {mode=mode,generation=Guid.NewGuid().ToString("N"),startedAt=now,deadline=now+10800,budgetYuan=5});
  }
 }
}
