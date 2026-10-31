using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Markup;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace AiAudioMemory {
 public sealed class AudioSnapshot {
  public string Root,Recording,RecordingDetail,Model,Mode,Latency,Cost,Deadline,Health,Transcript,TranscriptMeta,Memory,Log,Diagnostic,MaterialPath;
  public bool RecordingHealthy;
  public List<TextRange> Ranges=new List<TextRange>();
  public List<CorrectionNote> Annotations=new List<CorrectionNote>();
 }
 public sealed class AudioPane : AiWorkbench.IWorkbenchModule {
  readonly VisualVocabularyPane vocabulary; readonly SceneCameraPane camera;
  bool? previousClassroomEnabled;bool previousClassroomDraining;
  readonly string packageRoot;readonly BackgroundWorker worker=new BackgroundWorker(),catalogWorker=new BackgroundWorker(),subtitleDecisionWorker=new BackgroundWorker();
  readonly DispatcherTimer timer=new DispatcherTimer();readonly ComboBox logs;readonly CheckBox follow;
  string subtitleConfirmationId="";
  string currentLog="cloud-asr.stdout.log",annotationSignature="",notesRootLoaded="",notesModelPending="";bool closed=true,editing;AudioSnapshot current,displayed;Popup annotationPopup,selectionPopup;
  public FrameworkElement View {get;private set;}
  public AudioPane(string root){
   packageRoot=root;using(var input=File.OpenRead(Path.Combine(root,"AudioPane.xaml")))View=(FrameworkElement)XamlReader.Load(input);
   vocabulary=new VisualVocabularyPane(root,()=>ResolveRuntime(packageRoot));((ContentControl)View.FindName("VocabularyHost")).Content=vocabulary.View;
   camera=new SceneCameraPane(root,ResolveRuntime(root)); ((ContentControl)View.FindName("CameraHost")).Content=camera.View;
   logs=(ComboBox)View.FindName("LogPicker");follow=(CheckBox)View.FindName("Follow");
   foreach(string file in new[]{"cloud-asr.stdout.log","cloud-asr.stderr.log","recorder.stdout.log","recorder.stderr.log","transcriber.stdout.log","transcriber.stderr.log","extract.stdout.log","extract.stderr.log","annotation-worker.stdout.log"})logs.Items.Add(file);
   logs.SelectedIndex=0;logs.SelectionChanged+=(s,e)=>{currentLog=Convert.ToString(logs.SelectedItem);Refresh();};
   Click("Refresh",Refresh);Click("OpenFolder",()=>{if(current!=null && Directory.Exists(current.Root))Process.Start(new ProcessStartInfo(current.Root){UseShellExecute=true});});
   Click("CopyPath",()=>{if(current!=null)Copy(current.MaterialPath,"已复制实时转写文件路径");});
   Click("CopyDiagnostic",()=>{if(current!=null)Copy(current.Diagnostic,"已复制诊断信息（不含录音正文和密钥）");});
   Click("Annotate",()=>Annotate(null));Click("SubmitAnnotations",SubmitAnnotations);
   Click("UseLocal",()=>SwitchTranscription("local"));Click("UseCloud",()=>SwitchTranscription("cloud"));
   Click("AcceptSubtitle",()=>SubmitSubtitleDecision("accept"));Click("RejectSubtitle",()=>SubmitSubtitleDecision("reject"));
   subtitleDecisionWorker.DoWork+=(sender,args)=>{
    var files=(string[])args.Argument;string registry=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"registry.mjs");
    using(var proc=Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Subtitle-User-Decision --desc \"用户确认字幕候选，完成自动退出\" -- \""+AudioControls.Python(files[0])+"\" \""+Path.Combine(files[0],"subtitle_decisions.py")+"\" --request \""+files[1]+"\""){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true})){
     if(!proc.WaitForExit(15000))throw new InvalidOperationException("确认尚未完成，请稍后查看；未自动重发");
     if(proc.ExitCode!=0)throw new InvalidOperationException("确认未应用："+proc.StandardError.ReadToEnd());
    }
   };
   subtitleDecisionWorker.RunWorkerCompleted+=(sender,args)=>View.Dispatcher.BeginInvoke(new Action(()=>{if(closed)return;Set("Feedback",args.Error==null?"确认已处理，字幕自动刷新":args.Error.Message);Refresh();}));
   Click("ToggleClassroom",ToggleClassroom);
   Click("StartSubtitle",()=>SubtitleMaintenance(true));Click("PauseSubtitle",()=>SubtitleMaintenance(false));
   Click("ReloadNotesSessions",ReloadNotesSessions);Click("SaveNotesSettings",()=>SaveNotes(false,false));Click("StartNotes",()=>SaveNotes(true,false));Click("PauseNotes",()=>SaveNotes(false,true));
   Click("GenerateContext",GenerateContext);Click("OpenContextCandidate",OpenContextCandidate);
   var tabs=(TabControl)View.FindName("ContentTabs");tabs.SelectionChanged+=(s,e)=>{if(Object.ReferenceEquals(e.Source,tabs))Set("Feedback",tabs.SelectedIndex==3?"点击开始后持续维护；暂停后停止新委派，已提交批次可能继续完成。":tabs.SelectedIndex==1?"批注统一提交后由AI修订，完成时正文自动更新。":"每2秒检查变化；关闭工具箱不停止录音。");};
   ((ComboBox)View.FindName("NotesSession")).SelectionChanged+=(s,e)=>{var session=((ComboBox)View.FindName("NotesSession")).SelectedItem as NoteSession;if(session==null)return;var models=(ComboBox)View.FindName("NotesModel");var choices=session.models??new List<NoteModel>{new NoteModel{id="",label="沿用会话模型"}};models.ItemsSource=choices;models.SelectedItem=choices.Find(m=>m.id==notesModelPending)??choices[0];};
   ((ComboBox)View.FindName("NotesModel")).SelectionChanged+=(s,e)=>{var model=((ComboBox)View.FindName("NotesModel")).SelectedItem as NoteModel;if(model!=null)notesModelPending=model.id;};
   catalogWorker.DoWork+=(s,e)=>{
    string runtime=Convert.ToString(e.Argument),bridge=Path.Combine(packageRoot,"notes-bridge.mjs"),file=Path.Combine(runtime,"out","note-maintenance","sessions.json");Directory.CreateDirectory(Path.GetDirectoryName(file));
    using(var process=Process.Start(new ProcessStartInfo("node.exe","\""+bridge+"\" sessions \""+file+"\" \""+runtime+"\""){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true})){if(!process.WaitForExit(10000)){process.Kill();throw new InvalidOperationException("会话列表读取超时");}if(process.ExitCode!=0)throw new InvalidOperationException("会话列表读取失败："+process.StandardError.ReadToEnd());}
    e.Result=new JavaScriptSerializer{MaxJsonLength=4*1024*1024}.Deserialize<List<NoteSession>>(File.ReadAllText(file));
   };
   catalogWorker.RunWorkerCompleted+=(s,e)=>View.Dispatcher.BeginInvoke(new Action(()=>{
    ((Button)View.FindName("ReloadNotesSessions")).IsEnabled=true;if(e.Error!=null){Set("NotesStatus",e.Error.Message);return;}
    var sessions=(List<NoteSession>)e.Result;var picker=(ComboBox)View.FindName("NotesSession");string selected=Convert.ToString(picker.SelectedValue);if(selected.Length==0&&current!=null)selected=AudioControls.Notes(current.Root).sessionId;
    picker.ItemsSource=sessions;picker.SelectedItem=sessions.Find(n=>n.id==selected)??sessions.Find(n=>n.name=="课业");
   }));
   Click("RemoveAnnotation",()=>{var note=((ListBox)View.FindName("Annotations")).SelectedItem as CorrectionNote;if(note!=null&&current!=null){Corrections.Remove(current.Root,note.id);Refresh();}});
   ((ListBox)View.FindName("Annotations")).MouseDoubleClick+=(s,e)=>{var note=((ListBox)View.FindName("Annotations")).SelectedItem as CorrectionNote;if(note!=null&&note.status!="applied"&&note.status!="submitted")Annotate(note);};
   var transcript=(TextBox)View.FindName("Transcript");
   transcript.SelectionChanged+=(s,e)=>{((Button)View.FindName("Annotate")).IsEnabled=transcript.SelectionLength>0;if(selectionPopup!=null)selectionPopup.IsOpen=false;};
   transcript.AddHandler(UIElement.MouseLeftButtonUpEvent,new MouseButtonEventHandler((s,e)=>{
    ShowSelectionAction();
   }),true);
   transcript.KeyUp+=(s,e)=>{if(e.Key==Key.Escape){if(selectionPopup!=null)selectionPopup.IsOpen=false;}else if((Keyboard.Modifiers&ModifierKeys.Shift)!=0)ShowSelectionAction();};
   View.PreviewMouseDown+=(s,e)=>{if(!transcript.IsMouseOver&&selectionPopup!=null)selectionPopup.IsOpen=false;};
   View.Unloaded+=(s,e)=>{if(selectionPopup!=null)selectionPopup.IsOpen=false;if(annotationPopup!=null)annotationPopup.IsOpen=false;};
   follow.Checked+=(s,e)=>((TextBox)View.FindName("Transcript")).ScrollToEnd();
   worker.DoWork+=(s,e)=>{var args=(string[])e.Argument;e.Result=ReadSnapshot(args[0],args[1],DateTime.Now);};
   worker.RunWorkerCompleted+=(s,e)=>View.Dispatcher.BeginInvoke(new Action(()=>{
    if(closed)return;
    if(e.Error!=null){Set("Health","读取失败："+e.Error.Message);return;}
    current=(AudioSnapshot)e.Result;
    try{Apply(current);}catch(Exception error){Set("Health","界面更新未完成："+error.Message);}
   }));
   timer.Interval=TimeSpan.FromSeconds(2);timer.Tick+=(s,e)=>Refresh();
  }
  void ReloadNotesSessions(){if(current==null||catalogWorker.IsBusy)return;((Button)View.FindName("ReloadNotesSessions")).IsEnabled=false;catalogWorker.RunWorkerAsync(current.Root);}
  void SubmitSubtitleDecision(string action){
   if(current==null||String.IsNullOrEmpty(subtitleConfirmationId)||subtitleDecisionWorker.IsBusy)return;
   string term=((TextBox)View.FindName("SubtitleTerm")).Text.Trim();if(action=="accept"&&(term.Length==0||term.Length>100))throw new ArgumentException("请填写最多100字的符号或术语");
   string folder=Path.Combine(current.Root,"out","subtitle-decisions");Directory.CreateDirectory(folder);string request=Path.Combine(folder,Guid.NewGuid().ToString("N")+".json");
   AudioControls.Save(request,new Dictionary<string,object>{{"id",subtitleConfirmationId},{"action",action},{"term",term}});subtitleDecisionWorker.RunWorkerAsync(new[]{current.Root,request});Set("Feedback","正在处理确认，原文版本变化时不会强行覆盖。");
  }
  void UpdateSubtitleConfirmation(string root){
   var all=Json(Path.Combine(root,"subtitle-confirmations.json"));object items;Dictionary<string,object> pending=null;
   if(all.TryGetValue("items",out items)&&items is Dictionary<string,object>)foreach(object value in ((Dictionary<string,object>)items).Values){var row=value as Dictionary<string,object>;if(row!=null&&S(row,"status")=="needs_confirmation"){pending=row;break;}}
   ((TabItem)((TabControl)View.FindName("ContentTabs")).Items[3]).Header=N(all,"pendingCount")>0?"字幕维护 · "+N(all,"pendingCount").ToString("0")+" 待确认":"字幕维护";
   var panel=(Border)View.FindName("SubtitleConfirmation");panel.Visibility=pending==null?Visibility.Collapsed:Visibility.Visible;
   if(pending==null){subtitleConfirmationId="";return;}
   if(subtitleConfirmationId!=S(pending,"id")){subtitleConfirmationId=S(pending,"id");((TextBox)View.FindName("SubtitleTerm")).Text=S(pending,"term");Set("SubtitleQuestion",S(pending,"question"));Set("SubtitleReason",S(pending,"reason"));}
   ((Button)View.FindName("AcceptSubtitle")).IsEnabled=!subtitleDecisionWorker.IsBusy;((Button)View.FindName("RejectSubtitle")).IsEnabled=!subtitleDecisionWorker.IsBusy;
  }
  void SubtitleMaintenance(bool start){
   if(current==null)throw new InvalidOperationException("录音项目未连接");
   string file=Path.Combine(current.Root,"subtitle-maintenance.json");var settings=Json(file);
   if(start){string notes=((TextBox)View.FindName("NotesRoot")).Text.Trim();if(AudioControls.Classroom(current.Root)&&!Directory.Exists(notes))throw new ArgumentException("请填写现有笔记目录");settings["notesRoot"]=notes;settings["lesson"]=((TextBox)View.FindName("NotesLesson")).Text.Trim();settings["startedAt"]=AudioControls.Now();settings["deadline"]=AudioControls.Now()+10800;settings["budgetYuan"]=5;}
   settings["enabled"]=start;AudioControls.Save(file,settings);
   if(start)try{
    string python=AudioControls.Python(current.Root),script=Path.Combine(current.Root,"subtitle_maintenance.py"),registry=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"registry.mjs");
    if(!File.Exists(script)||!File.Exists(python))throw new FileNotFoundException("字幕初筛运行文件缺失");
    Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Subtitle-Context-Maintenance --desc \"只读课程参考、字幕主动初筛；独立于笔记维护\" -- \""+python+"\" \""+script+"\""){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=current.Root});
   }catch{settings["enabled"]=false;AudioControls.Save(file,settings);throw;}
   Set("SubtitleStatus",start?"已启动字幕AI：只读课程资料，字幕初筛独立计费":"已请求停止字幕AI；在途核对可能完成");Refresh();
  }
  void SaveNotes(bool start,bool pause){
   if(current==null)throw new InvalidOperationException("录音项目未连接");var settings=AudioControls.Notes(current.Root);string previousScope=settings.notesRoot+"\n"+settings.lesson;
   if(pause){settings.enabled=false;AudioControls.Save(Path.Combine(current.Root,"notes-maintenance.json"),settings);Set("NotesStatus","已暂停新委派；已提交的当前批次可能继续完成。");return;}
   settings.notesRoot=((TextBox)View.FindName("NotesRoot")).Text.Trim();settings.description=((TextBox)View.FindName("NotesDescription")).Text.Trim();settings.sessionId=Convert.ToString(((ComboBox)View.FindName("NotesSession")).SelectedValue);settings.model=Convert.ToString(((ComboBox)View.FindName("NotesModel")).SelectedValue);settings.lesson=((TextBox)View.FindName("NotesLesson")).Text.Trim();
   settings.strategy=Convert.ToString(((ComboBoxItem)((ComboBox)View.FindName("NotesStrategy")).SelectedItem).Tag);
   if(previousScope!=settings.notesRoot+"\n"+settings.lesson)settings.startedAt=0;
   Guid id;if(!Directory.Exists(settings.notesRoot)||!Path.IsPathRooted(settings.notesRoot)||String.IsNullOrWhiteSpace(settings.description)||!Guid.TryParse(settings.sessionId,out id))throw new ArgumentException("请填写现有笔记目录、维护要求，并选择一个已有会话");
   if(start&&!AudioControls.Classroom(current.Root))throw new InvalidOperationException("请先开启上课模式");
   settings.enabled=start;if(start&&settings.startedAt<=0)settings.startedAt=AudioControls.Now();AudioControls.Save(Path.Combine(current.Root,"notes-maintenance.json"),settings);
   if(start){
    string python=AudioControls.Python(current.Root),script=Path.Combine(current.Root,"notes_maintenance.py"),bridge=Path.Combine(packageRoot,"notes-bridge.mjs"),registry=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"registry.mjs");
    try{if(!File.Exists(python)||!File.Exists(script)||!File.Exists(bridge)||!File.Exists(registry))throw new FileNotFoundException("课堂维护运行环境未安装完整");
     Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Classroom-Notes-Maintenance --desc \"用户启用的第五学期笔记维护，暂停后停止新委派\" -- \""+python+"\" \""+script+"\" --bridge \""+bridge+"\""){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=current.Root});
    }catch{settings.enabled=false;AudioControls.Save(Path.Combine(current.Root,"notes-maintenance.json"),settings);throw;}
   }
   Set("NotesStatus",start?"已启用：按新增课堂材料及PPT骨架变化维护笔记":"配置已保存，尚未派工");Refresh();
  }
  void ToggleClassroom(){
   if(current==null)throw new InvalidOperationException("录音项目未连接");bool enabled=!AudioControls.Classroom(current.Root);AudioControls.Classroom(current.Root,enabled);if(enabled){vocabulary.Open();camera.Open();ReloadNotesSessions();}else {vocabulary.Close();camera.Close();}ApplyClassroom(current.Root);if(enabled)((TabControl)View.FindName("WorkspaceTabs")).SelectedIndex=1;Refresh();
  }
  void ApplyClassroom(string root){
   bool enabled=AudioControls.Classroom(root);var state=Json(Path.Combine(root,"notes-maintenance-state.json"));bool draining=!enabled&&S(state,"active").Equals("True",StringComparison.OrdinalIgnoreCase);
   ((Button)View.FindName("ToggleClassroom")).Content=enabled?"结束上课模式":"开启上课模式";Set("ClassroomStatus",enabled?"已开启：现场采集、视觉词表与笔记AI可用。录音与转写在日常功能中查看。":draining?"课堂任务收尾中；已停止新派工":"尚未开启。课堂功能集中在此；日常录音与转写独立运行。");
   ((TabItem)View.FindName("ClassroomCameraTab")).Visibility=enabled?Visibility.Visible:Visibility.Collapsed;
   ((TabItem)View.FindName("ClassroomContextTab")).Visibility=Visibility.Visible;
   ((TabItem)View.FindName("ClassroomNotesTab")).Visibility=enabled||draining?Visibility.Visible:Visibility.Collapsed;((TabItem)View.FindName("ClassroomVisualTab")).Visibility=enabled?Visibility.Visible:Visibility.Collapsed;((Button)View.FindName("StartNotes")).IsEnabled=enabled;
   ((TabControl)View.FindName("ClassroomTabs")).Visibility=enabled||draining?Visibility.Visible:Visibility.Collapsed;
   ((Border)View.FindName("ClassroomGate")).Visibility=enabled||draining?Visibility.Collapsed:Visibility.Visible;
   if(draining)((TabControl)View.FindName("ClassroomTabs")).SelectedItem=View.FindName("ClassroomNotesTab");
   var workspace=(TabControl)View.FindName("WorkspaceTabs");
   if(previousClassroomEnabled==null&&enabled)workspace.SelectedIndex=1;
   if(!enabled&&!draining&&(previousClassroomEnabled==true||previousClassroomDraining)){workspace.SelectedIndex=0;((TabControl)View.FindName("ContentTabs")).SelectedIndex=0;}
   previousClassroomEnabled=enabled;previousClassroomDraining=draining;
  }
  void GenerateContext(){
   if(current==null)throw new InvalidOperationException("录音项目未连接");
   string python=AudioControls.Python(current.Root),script=Path.Combine(current.Root,"context_auto.py");
   if(!File.Exists(python)||!File.Exists(script))throw new FileNotFoundException("情景生成运行文件缺失");
   Process.Start(new ProcessStartInfo(python,"\""+script+"\" --once"){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=current.Root});
   Set("ContextStatus","正在生成候选；完成后会自动刷新，不会覆盖正式情景卡。");
  }
  void OpenContextCandidate(){
   if(current==null)return;string candidate=Path.Combine(current.Root,"out","context-auto","candidate.json");if(!File.Exists(candidate))throw new FileNotFoundException("尚未生成自动情景");Process.Start(new ProcessStartInfo(candidate){UseShellExecute=true});
  }
  void Click(string name,Action action){((Button)View.FindName(name)).Click+=(s,e)=>{try{action();}catch(Exception ex){Set("Feedback",ex.Message);}};}
  void Copy(string value,string message){Clipboard.SetText(value??"");Set("Feedback",message);}
  Rect SelectionAnchor(TextBox box,double width){
   Rect first=box.GetRectFromCharacterIndex(box.SelectionStart),last=box.GetRectFromCharacterIndex(box.SelectionStart+Math.Max(0,box.SelectionLength-1),true);
   if(first.IsEmpty||last.IsEmpty)return new Rect(12,12,1,22);
   return new Rect(first.Y==last.Y?first.X:8,first.Top,first.Y==last.Y?Math.Max(1,last.Right-first.X):Math.Max(1,box.ActualWidth-24),Math.Max(first.Height,last.Bottom-first.Top));
  }
  Popup Floating(FrameworkElement child,TextBox box,double width){
   View.UpdateLayout();box.UpdateLayout();
   var anchor=SelectionAnchor(box,width);double x=Math.Max(8,Math.Min(anchor.Left,Math.Max(8,box.ActualWidth-width-12)));
   // WPF's custom placement callback receives device-pixel sizes, not DIPs.
   var source=PresentationSource.FromVisual(box);var transform=source==null?Matrix.Identity:source.CompositionTarget.TransformToDevice;
   var topLeft=transform.Transform(anchor.TopLeft);var bottomRight=transform.Transform(anchor.BottomRight);double px=transform.Transform(new Point(x,0)).X,gap=8*transform.M22;
   return new Popup{Child=child,PlacementTarget=box,Placement=PlacementMode.Custom,AllowsTransparency=true,StaysOpen=true,PopupAnimation=SystemParameters.ClientAreaAnimation?PopupAnimation.Fade:PopupAnimation.None,
    CustomPopupPlacementCallback=(size,target,offset)=>new[]{
     new CustomPopupPlacement(new Point(px,bottomRight.Y+gap),PopupPrimaryAxis.Horizontal),
     new CustomPopupPlacement(new Point(px,topLeft.Y-size.Height-gap),PopupPrimaryAxis.Horizontal),
     new CustomPopupPlacement(new Point(bottomRight.X+gap,topLeft.Y-size.Height/2),PopupPrimaryAxis.Vertical),
     new CustomPopupPlacement(new Point(topLeft.X-size.Width-gap,topLeft.Y-size.Height/2),PopupPrimaryAxis.Vertical)}};
  }
  Button AnnotationButton(string label,bool primary){
   return new Button{Content=label,Style=(Style)View.FindResource(typeof(Button)),Padding=new Thickness(14,8,14,8),Margin=new Thickness(0),Background=primary?new SolidColorBrush(Color.FromRgb(36,39,45)):new SolidColorBrush(Color.FromRgb(241,242,245)),Foreground=primary?Brushes.White:new SolidColorBrush(Color.FromRgb(55,58,65))};
  }
  void ShowSelectionAction(){
   var box=(TextBox)View.FindName("Transcript");if(editing||box.SelectionLength==0)return;
   if(selectionPopup!=null)selectionPopup.IsOpen=false;
   var button=AnnotationButton("添加批注",true);button.Focusable=false;button.Click+=(s,e)=>{try{Annotate(null);}catch(Exception error){Set("Feedback",error.Message);}};
   var surface=new Border{Child=button,Padding=new Thickness(4),Background=Brushes.White,CornerRadius=new CornerRadius(12),BorderBrush=new SolidColorBrush(Color.FromRgb(224,226,231)),BorderThickness=new Thickness(1)};
   selectionPopup=Floating(surface,box,118);selectionPopup.IsOpen=true;
  }
  void CloseAnnotation(Popup popup){
   if(Object.ReferenceEquals(annotationPopup,popup)){annotationPopup=null;editing=false;}
   popup.IsOpen=false;Refresh();
  }
  void Annotate(CorrectionNote existing){
   if(current==null)return;
   if(editing)return;
   if(selectionPopup!=null)selectionPopup.IsOpen=false;
   var material=displayed??current;
   var box=(TextBox)View.FindName("Transcript");TextRange range=null;int start=0,length=0;
   if(existing==null){
    int end=box.SelectionStart+box.SelectionLength;
    range=material.Ranges.Find(r=>box.SelectionStart>=r.DisplayStart&&end<=r.DisplayStart+r.DisplayLength);
    if(range==null||box.SelectionLength==0){Set("Feedback","请在同一段正文内选择需要修改的词句");return;}
    string visible=range.Text.Replace("\n",Environment.NewLine);
    start=Corrections.Normalize(visible.Substring(0,box.SelectionStart-range.DisplayStart)).Length;
    length=Corrections.Normalize(box.SelectedText).Length;
   }
   string annotationRoot=material.Root;editing=true;
   try{
    double width=Math.Min(510,Math.Max(300,View.ActualWidth-36));
    var panel=new StackPanel{Margin=new Thickness(8)};NameScope.SetNameScope(panel,new NameScope());
    var surface=new Border{Width=width,Background=Brushes.White,CornerRadius=new CornerRadius(26),BorderThickness=new Thickness(1),BorderBrush=new SolidColorBrush(Color.FromRgb(224,226,230)),Child=panel};
    System.Windows.Documents.TextElement.SetFontFamily(surface,new FontFamily("Microsoft YaHei"));
    surface.ToolTip=existing==null?range.Text.Substring(start,length):existing.selected;
    var row=new Grid();row.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});row.ColumnDefinitions.Add(new ColumnDefinition());row.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});panel.Children.Add(row);
    string initial=existing==null?"":existing.instruction+(String.IsNullOrWhiteSpace(existing.replacement)?"":"；请替换为："+existing.replacement);
    var instruction=new TextBox{Text=initial,IsReadOnly=false,AcceptsReturn=true,TextWrapping=TextWrapping.Wrap,MinHeight=38,MaxHeight=130,Padding=new Thickness(7,9,7,9),FontSize=14,Background=Brushes.Transparent,BorderThickness=new Thickness(0),VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
    var input=new Grid();Grid.SetColumn(input,1);row.Children.Add(input);input.Children.Add(instruction);
    var placeholder=new TextBlock{Text="希望 AI 怎样修改？",Foreground=new SolidColorBrush(Color.FromRgb(160,163,170)),Margin=new Thickness(8,9,0,0),IsHitTestVisible=false,FontSize=14};input.Children.Add(placeholder);
    Action placeholderState=()=>placeholder.Visibility=instruction.Text.Length==0?Visibility.Visible:Visibility.Collapsed;instruction.TextChanged+=(s,e)=>placeholderState();placeholderState();
    panel.RegisterName("InstructionEditor",instruction);
    var error=new TextBlock{Foreground=Brushes.IndianRed,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(38,5,12,2),Visibility=Visibility.Collapsed};panel.Children.Add(error);
    var popup=Floating(surface,box,width);annotationPopup=popup;
    popup.Closed+=(s,e)=>{if(Object.ReferenceEquals(annotationPopup,popup)){annotationPopup=null;editing=false;Refresh();}};
    panel.PreviewKeyDown+=(s,e)=>{if(e.Key==Key.Escape){CloseAnnotation(popup);e.Handled=true;box.Focus();}};
    var cancel=AnnotationButton("×",false);cancel.ToolTip="取消";cancel.Padding=new Thickness(10,6,10,6);cancel.Background=Brushes.Transparent;cancel.VerticalAlignment=VerticalAlignment.Top;cancel.Click+=(s,e)=>{CloseAnnotation(popup);box.Focus();};row.Children.Add(cancel);panel.RegisterName("CancelAnnotation",cancel);
    var save=AnnotationButton("↑",true);save.ToolTip="保存批注（Enter）；Shift+Enter换行";save.VerticalAlignment=VerticalAlignment.Top;save.Padding=new Thickness(12,6,12,6);Grid.SetColumn(save,2);save.Click+=(s,e)=>{
     try{
      if(String.IsNullOrWhiteSpace(instruction.Text))throw new ArgumentException("请描述希望怎样修改");
      if(existing==null)Corrections.Add(annotationRoot,range,start,length,instruction.Text,"");else Corrections.Edit(annotationRoot,existing.id,instruction.Text,"");
      CloseAnnotation(popup);Set("Feedback","批注已保存，可继续圈选；在“修改批注”页统一提交");box.Focus();
     }catch(Exception ex){error.Text=ex.Message;error.Visibility=Visibility.Visible;}
    };row.Children.Add(save);panel.RegisterName("SaveAnnotation",save);panel.RegisterName("AnnotationError",error);
    instruction.PreviewKeyDown+=(s,e)=>{if(e.Key==Key.Enter&&(Keyboard.Modifiers&ModifierKeys.Shift)==0){save.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));e.Handled=true;}};
    popup.IsOpen=true;instruction.Dispatcher.BeginInvoke(DispatcherPriority.Input,new Action(()=>instruction.Focus()));
   }catch{editing=false;annotationPopup=null;throw;}
  }
  void SwitchTranscription(string mode){
   if(current==null||String.IsNullOrEmpty(current.Root))throw new InvalidOperationException("录音项目未连接");
   if(mode==current.Mode)return;
   string python=AudioControls.Python(current.Root),script=Path.Combine(current.Root,"cloud_asr_trial.py"),registry=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"registry.mjs");
   if(mode=="cloud"&&(!File.Exists(python)||!File.Exists(script)||!File.Exists(registry)))throw new FileNotFoundException("大模型转写运行环境不完整");
   AudioControls.Switch(current.Root,mode);
   if(mode=="cloud")try{Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Audio-Cloud-Transcription --desc \"用户选择的大模型转写，切回本地停止新请求\" -- \""+python+"\" \""+script+"\" --controlled"){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=current.Root});}catch{AudioControls.Switch(current.Root,"local");throw;}
   Set("Feedback",mode=="cloud"?"已选择2.0 Mini；正在启动，每次最多3小时、估算停止线5元":"已切回本地；不再发起新转写请求，已发送的一片可能仍返回并计费");Refresh();
  }
  void SubmitAnnotations(){
   if(current==null)return;
   string python=AudioControls.Python(current.Root),script=Path.Combine(current.Root,"annotation_worker.py"),registry=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"registry.mjs");
   if(!File.Exists(python)||!File.Exists(script)||!File.Exists(registry))throw new FileNotFoundException("修订执行器未安装完整");
   string batch=Corrections.Submit(current.Root);
   try{
    Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Audio-Annotation-Maintenance --desc \"课堂批注修订，完成自动注销\" -- \""+python+"\" \""+script+"\" --batch "+batch){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=current.Root});
    Set("Feedback","批注已提交，完成后正文会自动更新");
   }catch(Exception error){Corrections.FailBatch(current.Root,batch,error.Message);throw;}
   Refresh();
  }
  void Set(string name,string value){var text=(TextBlock)View.FindName(name);if(text.Text!=value)text.Text=value;}
  public void Open(){vocabulary.Open();camera.Open();closed=false;timer.Start();Refresh();}
  public void Close(){camera.Close();if(current!=null&&AudioControls.Classroom(current.Root))AudioControls.Classroom(current.Root,false);vocabulary.Close();closed=true;timer.Stop();if(selectionPopup!=null)selectionPopup.IsOpen=false;if(annotationPopup!=null)annotationPopup.IsOpen=false;}
  void Refresh(){if(closed)return;vocabulary.RefreshSuite();if(worker.IsBusy)return;worker.RunWorkerAsync(new[]{ResolveRuntime(packageRoot),currentLog});}
  public static string ResolveRuntime(string package){
   try{
   string direct=Path.GetDirectoryName(package);if(File.Exists(Path.Combine(direct,"recorder.py")))return direct;
   string host=AudioControls.ToolboxRoot(package);
   var config=Json(Path.Combine(host,"data","module-subscriptions.json"));object bindings,value;
   if(config.TryGetValue("bindings",out bindings) && bindings is Dictionary<string,object> && ((Dictionary<string,object>)bindings).TryGetValue("audio-memory",out value))return Path.GetFullPath(Convert.ToString(value));
   }catch(IOException){}catch(ArgumentException){}catch(InvalidOperationException){}
   return "";
  }
  void UpdateBody(string name,string text,bool tracking){
   var box=(TextBox)View.FindName(name);if(box.Text==text)return;
   double offset=box.VerticalOffset;bool atEnd=box.ExtentHeight-box.ViewportHeight-offset<30;
   int start=box.SelectionStart,length=box.SelectionLength;string selection=box.SelectedText,anchor="";
   // WPF can report a stale visible line while a wrapped document is relaying out.
   try{
    int visible=box.GetFirstVisibleLineIndex();
    if(visible>=0&&visible<box.LineCount){int index=box.GetCharacterIndexFromLineIndex(visible);if(index>=0&&index<box.Text.Length)anchor=box.Text.Substring(index,Math.Min(50,box.Text.Length-index));}
   }catch(ArgumentOutOfRangeException){}
   box.Text=text;
   int selected=selection.Length>0?text.IndexOf(selection,StringComparison.Ordinal):-1;
   if(selected>=0)start=selected;
   box.Select(Math.Min(start,box.Text.Length),Math.Min(length,Math.Max(0,box.Text.Length-start)));
   if(tracking&&atEnd&&length==0)box.ScrollToEnd();
   else{
    int index=anchor.Length>0?text.IndexOf(anchor,StringComparison.Ordinal):-1;
    try{
     if(index>=0){box.UpdateLayout();int line=box.GetLineIndexFromCharacterIndex(index);if(line>=0&&line<box.LineCount)box.ScrollToLine(line);else box.ScrollToVerticalOffset(offset);}
     else box.ScrollToVerticalOffset(offset);
    }catch(ArgumentOutOfRangeException){box.ScrollToVerticalOffset(offset);}
   }
  }
  void Apply(AudioSnapshot data){
   ApplyClassroom(data.Root??"");
   var autoState=Json(Path.Combine(data.Root??"","out","context-auto","state.json"));var candidate=Json(Path.Combine(data.Root??"","out","context-auto","candidate.json"));object body;string narrative="";if(candidate.TryGetValue("candidate",out body)&&body is Dictionary<string,object>){var content=(Dictionary<string,object>)body;object elements;if(content.TryGetValue("sixElements",out elements)&&elements is Dictionary<string,object>){var six=(Dictionary<string,object>)elements;string[] keys={"time","place","people","cause","process","result"};string[] labels={"时间","地点","人物","起因","经过","结果"};for(int i=0;i<keys.Length;i++){object entry;string value="未知";if(six.TryGetValue(keys[i],out entry)&&entry is Dictionary<string,object>){string v=S((Dictionary<string,object>)entry,"value");if(!String.IsNullOrWhiteSpace(v))value=v;}narrative+=labels[i]+"："+value+"\n\n";}}narrative+="情节：\n"+S(content,"narrative");}Set("ContextStatus","自动情景："+S(autoState,"status")+" · "+S(autoState,"message"));((TextBox)View.FindName("ContextNarrative")).Text=narrative;
   if(notesRootLoaded!=data.Root&&!String.IsNullOrEmpty(data.Root)){
    var settings=AudioControls.Notes(data.Root);((TextBox)View.FindName("NotesRoot")).Text=settings.notesRoot;((TextBox)View.FindName("NotesDescription")).Text=settings.description;((TextBox)View.FindName("NotesLesson")).Text=settings.lesson;notesModelPending=settings.model;
    foreach(ComboBoxItem option in ((ComboBox)View.FindName("NotesStrategy")).Items)if(Convert.ToString(option.Tag)==settings.strategy)((ComboBox)View.FindName("NotesStrategy")).SelectedItem=option;
    notesRootLoaded=data.Root;if(current!=null&&AudioControls.Classroom(data.Root))ReloadNotesSessions();
   }
   UpdateSubtitleConfirmation(data.Root??"");
   var subtitle=Json(Path.Combine(data.Root??"","subtitle-maintenance-state.json"));var subtitleConfig=Json(Path.Combine(data.Root??"","subtitle-maintenance.json"));
   bool subActive=S(subtitle,"active").Equals("True",StringComparison.OrdinalIgnoreCase);bool subEnabled=S(subtitleConfig,"enabled").Equals("True",StringComparison.OrdinalIgnoreCase);
   if(subActive&&N(subtitle,"pid")>0)try{if(Process.GetProcessById((int)N(subtitle,"pid")).HasExited)subActive=false;}catch(ArgumentException){subActive=false;}
   if(!subActive&&subEnabled&&AudioControls.Now()-N(subtitleConfig,"startedAt")>15){subEnabled=false;}
   ((Button)View.FindName("StartSubtitle")).IsEnabled=!subEnabled&&!subActive;((Button)View.FindName("PauseSubtitle")).IsEnabled=subEnabled||subActive;
   Set("SubtitleStatus",(subActive?"":"已停止 · ")+(subtitle.Count==0?"尚未启动字幕初筛":S(subtitle,"status"))+(String.IsNullOrEmpty(S(subtitle,"latestReason"))?"":" · "+S(subtitle,"latestReason"))+(String.IsNullOrEmpty(S(subtitle,"error"))?"":" · "+S(subtitle,"error")));
   var notesState=Json(Path.Combine(data.Root??"","notes-maintenance-state.json"));if(notesState.Count>0){
    string noteStatus=(AudioControls.Notes(data.Root).enabled?"":"已暂停 · ")+S(notesState,"status")+" · 已完成 "+N(notesState,"completedBatches").ToString("0")+" 批"+(String.IsNullOrEmpty(S(notesState,"latestSummary"))?"":"\n"+S(notesState,"latestSummary"))+(String.IsNullOrEmpty(S(notesState,"error"))?"":" · "+S(notesState,"error"));
    string job=S(notesState,"activeJobId");if(S(notesState,"active").Equals("True",StringComparison.OrdinalIgnoreCase)&&Regex.IsMatch(job,@"^classroom-[a-f0-9]{32}$")){
     string receipt=Path.Combine(AudioControls.ToolboxRoot(packageRoot),"modules","collaboration-canvas","data","workbuddy-dispatch",job+".json");
     if(File.Exists(receipt)&&new FileInfo(receipt).Length<1024*1024){var report=Json(receipt);if(S(report,"state")=="waiting-permission")noteStatus="维护AI需要工具确认，请在工作台对应会话中检查；当前材料保留";}
    }Set("NotesStatus",noteStatus);
   }
   foreach(string mode in new[]{"local","cloud"}){var button=(Button)View.FindName(mode=="local"?"UseLocal":"UseCloud");bool selected=data.Mode==mode;button.Background=selected?new SolidColorBrush(Color.FromRgb(42,46,54)):new SolidColorBrush(Color.FromRgb(238,239,242));button.Foreground=selected?Brushes.White:Brushes.DimGray;}
   foreach(string key in new[]{"Recording","RecordingDetail","Model","Latency","Cost","Deadline","Health","TranscriptMeta"})Set(key,Convert.ToString(typeof(AudioSnapshot).GetField(key).GetValue(data)));
   ((TextBlock)View.FindName("Recording")).Foreground=new SolidColorBrush((Color)ColorConverter.ConvertFromString(data.RecordingHealthy?"#27805B":"#A35A22"));
   // Keep the action and its text anchor stable while the user is annotating.
   if(!editing&&(selectionPopup==null||!selectionPopup.IsOpen)){UpdateBody("Transcript",data.Transcript,follow.IsChecked==true);displayed=data;}UpdateBody("Memory",data.Memory,false);UpdateBody("Logs",data.Log,false);
   string signature=new JavaScriptSerializer{MaxJsonLength=16*1024*1024}.Serialize(data.Annotations);
   if(signature!=annotationSignature){var list=(ListBox)View.FindName("Annotations");var selected=list.SelectedItem as CorrectionNote;list.ItemsSource=data.Annotations;if(selected!=null)list.SelectedItem=data.Annotations.Find(n=>n.id==selected.id);annotationSignature=signature;}
   int pending=data.Annotations.FindAll(n=>n.status=="draft"||n.status=="failed").Count,running=data.Annotations.FindAll(n=>n.status=="submitted").Count;
   Set("AnnotationStatus","待提交 "+pending+" · 修订中 "+running+" · 已修订 "+data.Annotations.FindAll(n=>n.status=="applied").Count+" · 双击可编辑");
   ((Button)View.FindName("SubmitAnnotations")).IsEnabled=pending>0&&running==0;
   ((Button)View.FindName("CopyPath")).IsEnabled=!String.IsNullOrEmpty(data.MaterialPath);
  }
  static Dictionary<string,object> Json(string file){
   if(!File.Exists(file))return new Dictionary<string,object>();
   string raw=Tail(file,1024*1024,false);return new JavaScriptSerializer{MaxJsonLength=1024*1024}.Deserialize<Dictionary<string,object>>(raw)??new Dictionary<string,object>();
  }
  static string S(Dictionary<string,object> d,string key){object value;return d.TryGetValue(key,out value)?Convert.ToString(value,CultureInfo.InvariantCulture):"";}
  static double N(Dictionary<string,object> d,string key){double value;return Double.TryParse(S(d,key),NumberStyles.Any,CultureInfo.InvariantCulture,out value)?value:0;}
  static DateTime Epoch(double seconds){return new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(seconds).ToLocalTime();}
  public static string Tail(string file,int limit,bool lines){
   if(!File.Exists(file))return "";
   using(var input=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){
    long offset=Math.Max(0,input.Length-limit);input.Seek(offset,SeekOrigin.Begin);
    using(var reader=new StreamReader(input,Encoding.UTF8,true)){
     if(offset>0&&lines)reader.ReadLine();return reader.ReadToEnd();
    }
   }
  }
  static bool Within(string root,string file){return Path.GetFullPath(file).StartsWith(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);}
  public static AudioSnapshot ReadSnapshot(string root,string log,DateTime now){
   var result=new AudioSnapshot{Root=root,Recording="未连接",RecordingDetail="请在模组管理设置录音项目目录",Model="未连接",Latency="暂无识别结果",Cost="—",Deadline="未读取云端试验",Health="录音项目目录未配置",Transcript="暂无实时转写",TranscriptMeta="暂无转写",Memory="今天尚未生成记忆结果",Log="暂无日志",Diagnostic="目录未配置",MaterialPath=""};
   if(String.IsNullOrEmpty(root)||!Directory.Exists(root))return result;
   string latest="",record=Path.Combine(root,"record");DateTime last=DateTime.MinValue;
   if(Directory.Exists(record))foreach(string file in Directory.GetFiles(record,"*.wav")){DateTime time=File.GetLastWriteTime(file);if(time>last){last=time;latest=file;}}
   double age=last==DateTime.MinValue?Double.PositiveInfinity:(now-last).TotalSeconds;
   result.RecordingHealthy=age<150;result.Recording=age<150?"正在采集":"录音未更新";
   result.RecordingDetail=latest.Length>0?"最近落盘 "+last.ToString("HH:mm:ss")+" · "+Math.Max(0,(int)age)+"秒前":"尚无录音文件";
   var state=Json(Path.Combine(root,"cloud-asr-trial.json"));double deadline=N(state,"deadline");bool legacyActive=S(state,"active").Equals("True",StringComparison.OrdinalIgnoreCase)&&deadline>0&&Epoch(deadline)>now;
   result.Mode=AudioControls.Mode(root,legacyActive);var selectedMode=AudioControls.Read(root);bool active=legacyActive&&result.Mode=="cloud"&&(selectedMode.Count==0||S(selectedMode,"generation")==S(state,"generation"));
   string day=now.ToString("yyyyMMdd"),local=Path.Combine(root,"out",day),source=local;bool cloud=false;
   string candidate=S(state,"latestDayDir");
   if(active&&candidate.Length>0&&Within(Path.Combine(root,"out"),candidate)&&File.Exists(Path.Combine(candidate,"timeline.jsonl"))&&(now-File.GetLastWriteTime(Path.Combine(candidate,"timeline.jsonl"))).TotalSeconds<90){source=candidate;cloud=true;}
   result.Model=cloud?ModelLabel(S(state,"model")):"本地 Whisper";
   result.Latency=cloud?"接口 "+N(state,"latestLatencySeconds").ToString("0.00")+"秒 · 15秒整片转写":active?"云端等待更新，显示本地材料":"持续转写 · 云端试验未运行";
   result.Cost=state.Count>0?"¥ "+N(state,"estimatedYuan").ToString("0.000"):"未开始";
   result.Deadline=deadline>0?(active?"试验至 ":"原截止 ")+Epoch(deadline).ToString("HH:mm:ss")+" · 估算停止线 ¥"+N(state,"budgetYuan").ToString("0.##"):"费用含请求预留，以账户账单为准";
   string timeline=Path.Combine(source,"timeline.jsonl");result.MaterialPath=File.Exists(timeline)?timeline:"";
   var chunks=Tail(timeline,128*1024,true).Split(new[]{'\n'},StringSplitOptions.RemoveEmptyEntries);var rows=new List<Dictionary<string,object>>();var parser=new JavaScriptSerializer{MaxJsonLength=512*1024};
   foreach(string line in chunks){try{var row=parser.Deserialize<Dictionary<string,object>>(line);if(!String.IsNullOrWhiteSpace(S(row,"text")))rows.Add(row);}catch{}}
   var corrections=Corrections.Read(root);result.Annotations=corrections.annotations;
   int begin=Math.Max(0,rows.Count-100);var body=new StringBuilder();
   for(int i=begin;i<rows.Count;i++){
    var row=rows[i];string raw=Corrections.Normalize(S(row,"text")),key=Corrections.Key(timeline,S(row,"file"),N(row,"start"),N(row,"end"));CorrectionRecord corrected;
    string effective=raw;int revision=0;
    if(corrections.records.TryGetValue(key,out corrected)&&corrected.original==raw){effective=corrected.text;revision=corrected.revision;}
    body.Append(S(row,"t")).Append("   ");string rendered=effective.Replace("\n",Environment.NewLine);
    result.Ranges.Add(new TextRange{Id=key,Source=timeline,File=S(row,"file"),Original=raw,Text=effective,Start=N(row,"start"),End=N(row,"end"),Revision=revision,DisplayStart=body.Length,DisplayLength=rendered.Length});
    body.Append(rendered).AppendLine().AppendLine();
   }
   result.Transcript=body.Length>0?body.ToString():"尚未收到可识别的课堂语音。";
   DateTime transTime=File.Exists(timeline)?File.GetLastWriteTime(timeline):DateTime.MinValue;
   result.TranscriptMeta=(cloud?"云端":"本地")+" · 最近"+(rows.Count-begin)+"段"+(transTime>DateTime.MinValue?" · 更新 "+transTime.ToString("HH:mm:ss"):"")+ (cloud?" · 时间为分片起点":"");
   int revised=result.Ranges.FindAll(r=>r.Revision>0).Count;if(revised>0)result.TranscriptMeta+=" · 已修订 "+revised+"段";
   result.Memory=Tail(Path.Combine(local,"memory.md"),128*1024,true);if(result.Memory.Length==0)result.Memory="今天尚未生成记忆结果。";
   var notices=new List<string>();
   if(!result.RecordingHealthy)notices.Add("录音超过150秒未落盘，请查看录音错误日志");
   if(active&&!cloud)notices.Add("云端尚无新结果或超过90秒未更新，当前显示本地转写");
   if(transTime==DateTime.MinValue||(now-transTime).TotalSeconds>120)notices.Add("转写暂未更新，可能正在等待内存或处理队列");
   if(!active && state.Count>0)notices.Add(S(state,"stopReason")=="consecutive_failures"?"云端因连续网络失败停止，本地采集独立运行":"云端试验已停止或已到期，本地采集独立运行");
   if(active&&S(state,"recovering").Equals("True",StringComparison.OrdinalIgnoreCase))notices.Add("云端网络异常，正在退避重试");
   result.Health=notices.Count>0?String.Join("；",notices.ToArray()):"录音与转写正在更新 · 云端成功 "+Count(state,"completed")+"片 · 费用为估算，包含在途请求预留";
   if(log!=Path.GetFileName(log)||!Regex.IsMatch(log,@"^(cloud-asr|recorder|transcriber|extract|annotation-worker)\.(stdout|stderr)\.log$"))throw new InvalidOperationException("无效日志文件");
   result.Log=Tail(Path.Combine(root,log),48*1024,true);if(result.Log.Length==0)result.Log="这份日志暂无内容。";
   result.Log=Regex.Replace(result.Log,@"(?i)Bearer\s+[^\s""']+","Bearer [已隐藏]");
   result.Diagnostic="录音项目："+root+Environment.NewLine+result.Recording+" · "+result.RecordingDetail+Environment.NewLine+result.Model+" · "+result.Latency+Environment.NewLine+"费用估算："+result.Cost+"；"+result.Deadline+Environment.NewLine+result.Health+Environment.NewLine+"材料："+result.MaterialPath;
   return result;
  }
  static int Count(Dictionary<string,object> d,string key){object value;return d.TryGetValue(key,out value)&&value is ArrayList?((ArrayList)value).Count:0;}
  static string ModelLabel(string id){if(id.Contains("seed-2-0-mini"))return "豆包 2.0 Mini";if(id.Contains("seed-2-1-lite"))return "豆包 2.1 Lite";return id.Length>0?id:"云端 ASR";}
 }
}
