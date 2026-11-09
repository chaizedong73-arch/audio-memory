using System;
using System.IO;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Media.Animation;
using System.Windows.Markup;
using System.Windows.Shapes;

namespace AiAudioMemory {
 public sealed class VocabularyModel {public string id{get;set;}public string label{get;set;}public string task{get;set;}public bool? ready{get;set;}}
 public sealed class ExperimentCase {public string id{get;set;}public string label{get;set;}public string image{get;set;}public string ocrGold{get;set;}public string visionGold{get;set;}}
 public sealed class ExperimentSuite {public int version{get;set;}public string selectionPolicy{get;set;}public List<ExperimentCase> cases{get;set;}}
 public sealed class VocabularyWord {
  public string text{get;set;}public string kind{get;set;}public double[] bbox{get;set;}public bool uncertain{get;set;}
  public string ReviewLabel{get{return uncertain?"待核对":"未验证";}}
  public string KindLabel{get{switch((kind??"").ToLowerInvariant()){case "text":case "body":return "正文";case "abbreviation":return "缩写";case "symbol":return "符号";case "formula":return "公式";case "title":case "heading":return "标题";case "number":return "数字";default:return kind;}}}
 }
 public sealed class VocabularyResult {
  public List<Dictionary<string,object>> elements{get;set;}public List<Dictionary<string,object>> visualRelations{get;set;}public string rawAnswer{get;set;}public Dictionary<string,object> benchmark{get;set;}public string experimentDocument{get;set;}public string task{get;set;}public string model{get;set;}public string text{get;set;}public string error{get;set;}public double elapsedSeconds{get;set;}public bool cached{get;set;}
  public List<VocabularyWord> words{get;set;}public List<VocabularyWord> groups{get;set;}public string readingText{get;set;}public Dictionary<string,object> usage{get;set;}
 }
 public sealed class VisualVocabularyPane {
  public FrameworkElement View{get;private set;}
  readonly Func<string> runtime;readonly string registry;
  readonly BackgroundWorker worker=new BackgroundWorker();readonly object gate=new object();
  Process active;volatile bool cancelled;bool closed,testInput;
  string image="",lastJson="",operation="",currentRequest="";int width,height;
  List<VocabularyModel> allModels=new List<VocabularyModel>();ExperimentSuite suite;bool loadingCase;string suiteText="";
  static JavaScriptSerializer Json{get{return new JavaScriptSerializer{MaxJsonLength=20*1024*1024};}}
  public VisualVocabularyPane(string package,Func<string> resolve){
   runtime=resolve;registry=System.IO.Path.Combine(AudioControls.ToolboxRoot(package),"registry.mjs");
   using(var input=File.OpenRead(System.IO.Path.Combine(package,"VisualVocabulary.xaml")))View=(FrameworkElement)XamlReader.Load(input);
   Button("PickImage",()=>{var dialog=new Microsoft.Win32.OpenFileDialog{Filter="图片|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff"};if(dialog.ShowDialog()==true)LoadImage(dialog.FileName,true);});
   Button("PasteImage",()=>{if(!Clipboard.ContainsImage())throw new InvalidOperationException("剪贴板中没有图片");LoadBitmap(Clipboard.GetImage(),"粘贴截图",true);});
   Button("ConfigureModels",()=>Process.Start(new ProcessStartInfo("notepad.exe",System.IO.Path.Combine(runtime(),"visual-lab-providers.json")){UseShellExecute=true}));
   ((ComboBox)View.FindName("TaskMode")).SelectionChanged+=(s,e)=>{if(!worker.IsBusy){FilterModels();TryCached();}};
   ((ComboBox)View.FindName("Cases")).SelectionChanged+=(s,e)=>{if(!worker.IsBusy)LoadCase();};
   Button("Run",()=>Start(false));Button("ReloadModels",()=>Start(true));Button("Cancel",Cancel);
   Button("CopyResult",()=>Clipboard.SetText(lastJson));Button("OpenResults",()=>{var folder=Folder();Directory.CreateDirectory(folder);Process.Start(new ProcessStartInfo(folder){UseShellExecute=true});});
   Button("OpenLedger",()=>{string path=System.IO.Path.Combine(Folder(),"experiment","实验记录.md");if(!File.Exists(path))throw new InvalidOperationException("正式实验尚未产生记录");Process.Start(new ProcessStartInfo("notepad.exe","\""+path+"\""){UseShellExecute=true});});
   View.DragOver+=(s,e)=>{e.Effects=e.Data.GetDataPresent(DataFormats.FileDrop)&&!worker.IsBusy?DragDropEffects.Copy:DragDropEffects.None;e.Handled=true;};
   View.Drop+=(s,e)=>{if(worker.IsBusy)return;try{var files=e.Data.GetData(DataFormats.FileDrop) as string[];if(files!=null&&files.Length>0)LoadImage(files[0],true);}catch(Exception error){Status(error.Message);}};
   ((ComboBox)View.FindName("Models")).SelectionChanged+=(s,e)=>{if(!worker.IsBusy){TryCached();UpdateSuiteStatus();}};
   ((DataGrid)View.FindName("Words")).SelectionChanged+=(s,e)=>Highlight();
   worker.DoWork+=Work;
   worker.RunWorkerCompleted+=(s,e)=>View.Dispatcher.BeginInvoke(new Action(()=>{
    if(cancelled&&operation!="models")RecordInterrupted("用户取消或关闭展示窗口");
    if(e.Error!=null&&operation!="models")RecordInterrupted(e.Error.Message);
    if(closed)return;SetBusy(false);
    try{if(cancelled){Status("已取消 · 可再次提取，原图与上次结果保留");return;}
     if(e.Error!=null){Status("未完成："+e.Error.Message+" · 可换模型重试");return;}
     if(operation=="models"){LoadModels();Status("模型目录已刷新；目录可见不代表账号已开通");}
     else ShowResult(Convert.ToString(e.Result));
    }catch(Exception error){Status("结果无法显示："+error.Message);}
   }));LoadModels();LoadSuite();
   View.PreviewMouseWheel+=(s,e)=>{
    DependencyObject node=e.OriginalSource as DependencyObject;ScrollViewer inner=null;
    while(node!=null){inner=node as ScrollViewer;if(inner!=null)break;try{node=VisualTreeHelper.GetParent(node);}catch(InvalidOperationException){break;}}
    var outer=(ScrollViewer)View;
    if(inner!=null&&inner!=outer&&inner.ScrollableHeight>0&&((e.Delta<0&&inner.VerticalOffset<inner.ScrollableHeight-.5)||(e.Delta>0&&inner.VerticalOffset>.5)))return;
    outer.ScrollToVerticalOffset(outer.VerticalOffset-e.Delta/3.0);e.Handled=true;
   };
  }
  string Folder(){string root=runtime();if(String.IsNullOrEmpty(root)||!Directory.Exists(root))throw new InvalidOperationException("请先配置录音记忆运行目录");return System.IO.Path.Combine(root,"out","visual-vocabulary");}
  ExperimentCase CurrentCase{get{return ((ComboBox)View.FindName("Cases")).SelectedItem as ExperimentCase;}}
  bool SuiteReady{get{return suite!=null&&suite.cases!=null&&suite.cases.Count==3&&suite.cases.TrueForAll(c=>File.Exists(c.image??"")&&File.Exists(c.ocrGold??"")&&File.Exists(c.visionGold??""));}}
  void LoadSuite(){
   string file=System.IO.Path.Combine(runtime(),"visual-experiment-suite.json");if(!File.Exists(file))return;
   string text=File.ReadAllText(file);var parsed=Json.Deserialize<ExperimentSuite>(text);if(parsed==null||parsed.cases==null||parsed.cases.Count!=3)throw new InvalidOperationException("实验配置不完整");string selected=CurrentCase==null?"complex":CurrentCase.id;suite=parsed;suiteText=text;var combo=(ComboBox)View.FindName("Cases");combo.ItemsSource=suite.cases;combo.SelectedItem=suite.cases.Find(c=>c.id==selected)??suite.cases[0];
  }
  public void RefreshSuite(){
   if(closed||worker.IsBusy)return;try{string file=System.IO.Path.Combine(runtime(),"visual-experiment-suite.json");if(File.Exists(file)&&File.ReadAllText(file)!=suiteText)LoadSuite();else UpdateSuiteStatus();}catch(Exception error){Status("实验配置刷新失败："+error.Message);((Button)View.FindName("Run")).IsEnabled=false;}
  }
  void LoadCase(){
   var c=CurrentCase;if(c==null)return;
   if(!String.IsNullOrEmpty(c.image)&&File.Exists(c.image)){loadingCase=true;try{LoadImage(c.image,false);testInput=false;}finally{loadingCase=false;}}
   else{image="";((Image)View.FindName("Preview")).Source=null;((Canvas)View.FindName("Markers")).Children.Clear();((DataGrid)View.FindName("Words")).ItemsSource=null;((TextBox)View.FindName("FullText")).Clear();((TextBox)View.FindName("RawText")).Clear();((TextBox)View.FindName("Scoring")).Clear();((TextBlock)View.FindName("ImageName")).Text=c.label+" · 待选择图片";((Button)View.FindName("Run")).IsEnabled=false;}
   UpdateSuiteStatus();
  }
  void UpdateSuiteStatus(){
   if(suite==null)return;var text=new StringBuilder();foreach(var c in suite.cases){text.Append(c.id=="simple"?"简单":c.id=="medium"?"中级":"复杂");text.Append(String.IsNullOrEmpty(c.image)?"：待选图  ":File.Exists(c.ocrGold??"")&&File.Exists(c.visionGold??"")?"：图与两份答案已备  ":"：待GPT核对答案  ");}text.Append(SuiteReady?"· 可以手动测试":"· 准备齐三图与答案后开放正式测试");((TextBlock)View.FindName("SuiteStatus")).Text=text.ToString();
   var selected=((ComboBox)View.FindName("Models")).SelectedItem as VocabularyModel;((Button)View.FindName("Run")).IsEnabled=AudioControls.Classroom(runtime())&&!worker.IsBusy&&SuiteReady&&!String.IsNullOrEmpty(image)&&selected!=null&&selected.ready!=false;
  }
  void AssignCase(){
   if(loadingCase||CurrentCase==null)return;CurrentCase.image=image;CurrentCase.ocrGold="";CurrentCase.visionGold="";CurrentCase.label=(CurrentCase.id=="simple"?"简单图":CurrentCase.id=="medium"?"中级图":"复杂图")+" · 待核对答案";AudioControls.Save(System.IO.Path.Combine(runtime(),"visual-experiment-suite.json"),suite);UpdateSuiteStatus();
  }
  void RestoreLast(){
   try{
    string folder=Folder(),runs=System.IO.Path.Combine(folder,"runs");if(!Directory.Exists(runs))return;
    var files=new List<string>(Directory.GetFiles(runs,"request.json",SearchOption.AllDirectories));files.Sort((a,b)=>File.GetLastWriteTimeUtc(b).CompareTo(File.GetLastWriteTimeUtc(a)));
    foreach(string request in files){
     string output=System.IO.Path.Combine(System.IO.Path.GetDirectoryName(request),"result.json");if(!File.Exists(output))continue;
     var result=Json.Deserialize<VocabularyResult>(File.ReadAllText(output));if(!String.IsNullOrEmpty(result.error))continue;
     var job=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(request));string source=System.IO.Path.GetFullPath(Convert.ToString(job["image"]));
     object fixture;if(job.TryGetValue("testFixture",out fixture)&&Convert.ToBoolean(fixture))continue;
     if(!source.StartsWith(System.IO.Path.GetFullPath(folder)+System.IO.Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||!File.Exists(source))continue;
     LoadImage(source,false);testInput=false;((ComboBox)View.FindName("TaskMode")).SelectedIndex=result.task=="vision"?1:0;((ComboBox)View.FindName("Models")).SelectedValue=result.model;ShowResult(File.ReadAllText(output),true);Status("已恢复上次结果 · 可滚动查看，或换图继续测试");break;
    }
   }catch(Exception error){Status("上次结果未恢复："+error.Message);}
  }
  void Button(string name,Action action){((Button)View.FindName(name)).Click+=(s,e)=>{try{action();}catch(Exception error){Status(error.Message);}};}
  void Status(string text){((TextBlock)View.FindName("Status")).Text=text;}
  string ModelLabel(string id){foreach(VocabularyModel model in ((ComboBox)View.FindName("Models")).Items)if(model.id==id)return model.label;return id;}
  public void LoadImage(string path,bool archive){
   if(worker.IsBusy)return;var bitmap=new BitmapImage();bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.UriSource=new Uri(System.IO.Path.GetFullPath(path));bitmap.EndInit();bitmap.Freeze();
   testInput=!archive;if(archive)Archive(path);LoadBitmap(bitmap,System.IO.Path.GetFileName(path),false);
  }
  void Archive(string path){
   string folder=System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),"WorkBuddy","2026-09-11-15-44-25",".workbuddy","原材料",DateTime.Now.ToString("yyyy-MM-dd"));
   Directory.CreateDirectory(folder);File.Copy(path,System.IO.Path.Combine(folder,"视觉词表-"+Guid.NewGuid().ToString("N")+System.IO.Path.GetExtension(path)));
  }
  void LoadBitmap(BitmapSource bitmap,string name,bool archive){
   if(archive)testInput=false;
   if(bitmap.PixelWidth*(long)bitmap.PixelHeight>64000000)throw new InvalidOperationException("图片过大，请先缩小到6400万像素以内");
   BitmapSource normalized=bitmap;double scale=Math.Min(1,2500.0/Math.Max(bitmap.PixelWidth,bitmap.PixelHeight));if(scale<1)normalized=new TransformedBitmap(bitmap,new ScaleTransform(scale,scale));width=normalized.PixelWidth;height=normalized.PixelHeight;
   string folder=System.IO.Path.Combine(Folder(),"inputs",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);image=System.IO.Path.Combine(folder,"input.png");
   var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(normalized));using(var file=File.Create(image))encoder.Save(file);if(archive){string original=System.IO.Path.Combine(folder,"original.png");var originalEncoder=new PngBitmapEncoder();originalEncoder.Frames.Add(BitmapFrame.Create(bitmap));using(var raw=File.Create(original))originalEncoder.Save(raw);Archive(original);}
   var surface=(Grid)View.FindName("ImageSurface");surface.Width=width;surface.Height=height;((Image)View.FindName("Preview")).Source=normalized;
   ((TextBlock)View.FindName("ImageName")).Text=name+" · "+width+" × "+height;((TextBlock)View.FindName("ImageName")).ToolTip=image;
   ((TextBlock)View.FindName("EmptyImage")).Visibility=Visibility.Collapsed;((Canvas)View.FindName("Markers")).Children.Clear();((Button)View.FindName("Run")).IsEnabled=true;
   ((DataGrid)View.FindName("Words")).ItemsSource=null;((TextBox)View.FindName("FullText")).Text="";lastJson="";((Button)View.FindName("CopyResult")).IsEnabled=false;
   if(SystemParameters.ClientAreaAnimation)((Image)View.FindName("Preview")).BeginAnimation(UIElement.OpacityProperty,new DoubleAnimation(0,1,TimeSpan.FromMilliseconds(180)));
   if(!testInput)AssignCase();
   TryCached();Status("图片已就绪 · 选择模型并提取");
  }
  void LoadModels(){
   var list=new List<VocabularyModel>{new VocabularyModel{id="local:windows",label="Windows OCR · 系统引擎"},new VocabularyModel{id="doubao-seed-2-0-mini-260428",label="豆包 2.0 Mini · 云端轻量"},new VocabularyModel{id="doubao-seed-2-0-lite-260428",label="豆包 2.0 Lite · 云端"},new VocabularyModel{id="doubao-seed-2-0-pro-260215",label="豆包 2.0 Pro · 云端（退役中）"},new VocabularyModel{id="doubao-seed-2-1-pro-260915",label="豆包 2.1 Pro · 云端（较高费用）"}};
   try{string path=System.IO.Path.Combine(Folder(),"models.json");if(File.Exists(path))list=Json.Deserialize<List<VocabularyModel>>(File.ReadAllText(path));}catch{}
   allModels=list;FilterModels();
  }
  void FilterModels(){
   bool vision=((ComboBox)View.FindName("TaskMode")).SelectedIndex==1;
   var list=allModels.FindAll(x=>vision ? (x.task=="vision" || (x.task==null && !x.id.StartsWith("local:"))) : (x.task=="ocr" || (x.task==null && x.id.StartsWith("local:"))));
   var combo=(ComboBox)View.FindName("Models");string selected=Convert.ToString(combo.SelectedValue);combo.ItemsSource=list;combo.SelectedItem=list.Find(x=>x.id==selected)??(list.Count>0?list[0]:null);
  }
  void TryCached(){
   if(((CheckBox)View.FindName("Cache")).IsChecked!=true){Status("等待手动执行 · 不自动运行或复用上轮答案");return;}
   if(((ComboBox)View.FindName("TaskMode")).SelectedIndex==1){Status("图形与结构 · 选择视觉模型后运行，保留上次结果供对照");return;}
   if(String.IsNullOrEmpty(image)||!File.Exists(image))return;
   try{var choice=((ComboBox)View.FindName("Models")).SelectedItem as VocabularyModel;if(choice==null)return;string model=choice.id;string hash;
    using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(image))).Replace("-","").ToLowerInvariant();
    if(model.StartsWith("custom:")){Status("自定义模型 · 运行时检查对应缓存");return;}
    string key;using(var sha=SHA256.Create())key=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes("visual-vocabulary-1|"+hash+"|"+model))).Replace("-","").ToLowerInvariant();
    string path=System.IO.Path.Combine(Folder(),"cache",key+".json");
    if(File.Exists(path))ShowResult(File.ReadAllText(path),true);else {((TextBlock)View.FindName("ResultMeta")).Text=String.IsNullOrEmpty(lastJson)?"当前模型尚未测试":"上次结果 · "+ModelLabel(Json.Deserialize<VocabularyResult>(lastJson).model);Status("当前所选模型尚未运行，点击提取词表");}
   }catch(Exception error){Status(error.Message);}
  }
  void SetBusy(bool busy){
   foreach(string name in new[]{"PickImage","PasteImage","Models","ReloadModels","Cache","TaskMode","ConfigureModels","Cases"})((Control)View.FindName(name)).IsEnabled=!busy;
   UpdateSuiteStatus();((Button)View.FindName("Cancel")).IsEnabled=busy;((ProgressBar)View.FindName("Busy")).Visibility=busy?Visibility.Visible:Visibility.Collapsed;
  }
  void Start(bool catalog){
   if(worker.IsBusy)return;closed=false;cancelled=false;string root=runtime(),file;
   if(catalog){file=System.IO.Path.Combine(Folder(),"models.json");operation="models";SetBusy(true);Status("正在读取模型目录，不调用图像模型");worker.RunWorkerAsync(new[]{root,"--models",file});return;}
   if(String.IsNullOrEmpty(image))throw new InvalidOperationException("请先选择图片");var model=((ComboBox)View.FindName("Models")).SelectedItem as VocabularyModel;if(model==null)throw new InvalidOperationException("请选择模型");
   if(!AudioControls.Classroom(runtime()))throw new InvalidOperationException("请先开启上课模式");
   if(!SuiteReady)throw new InvalidOperationException("先备齐你选定的三张图片与两路标准答案，再开始正式实验");
   if(((ComboBox)View.FindName("TaskMode")).SelectedIndex==1&&model.id.StartsWith("local:"))throw new InvalidOperationException("专用OCR不能理解图形，请选择视觉模型");
   bool vision=((ComboBox)View.FindName("TaskMode")).SelectedIndex==1;
   if(!vision&&!model.id.StartsWith("local:"))throw new InvalidOperationException("OCR实验只允许本地模型");
   if(model.ready==false)throw new InvalidOperationException("模型尚未就绪，请等待下载完成后刷新模型");
   if(CurrentCase!=null&&!File.Exists((vision?CurrentCase.visionGold:CurrentCase.ocrGold)??""))throw new InvalidOperationException("这张图片的标准答案尚未准备好，请先由GPT核对答案；图片已经保存");
   operation=model.id;string folder=System.IO.Path.Combine(Folder(),"runs",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(folder);file=System.IO.Path.Combine(folder,"request.json");
   currentRequest=file;
   AudioControls.Save(file,new Dictionary<string,object>{{"image",image},{"width",width},{"height",height},{"model",model.id},{"caseId",CurrentCase==null?"unassigned":CurrentCase.id},{"task",vision?"vision":"ocr"},{"cache",((CheckBox)View.FindName("Cache")).IsChecked==true},{"testFixture",testInput}});
   SetBusy(true);Status("正在提取 · "+model.label);worker.RunWorkerAsync(new[]{root,"--request \""+file+"\"",System.IO.Path.Combine(folder,"result.json")});
  }
  void Work(object sender,DoWorkEventArgs e){
   var args=(string[])e.Argument;string name="Visual-Vocabulary-"+Guid.NewGuid().ToString("N").Substring(0,10);
   try{
    var info=new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name "+name+" --desc \"单图视觉词表测试，完成自动退出\" -- \""+AudioControls.Python(args[0])+"\" \""+System.IO.Path.Combine(AudioControls.CodeRoot(args[0]),"visual_vocabulary_test.py")+"\" "+args[1]+AudioControls.RootArgument(args[0])){UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true,RedirectStandardOutput=true};
    lock(gate){if(cancelled)return;active=Process.Start(info);}
    // Drain both pipes while the model runs; full pipes must not freeze a test.
    var stdout=active.StandardOutput.ReadToEndAsync();var stderr=active.StandardError.ReadToEndAsync();
    if(!active.WaitForExit(operation.StartsWith("local-vlm:")?600000:70000)){Kill();throw new InvalidOperationException("测试超时，已结束本次进程，可换模型重试");}
    if(cancelled)return;
    if(active.ExitCode!=0){if(File.Exists(args[2])){var failure=Json.Deserialize<VocabularyResult>(File.ReadAllText(args[2]));if(!String.IsNullOrEmpty(failure.error))throw new InvalidOperationException(failure.error);}throw new InvalidOperationException("模型调用失败，请检查开通状态与网络；未切换到其他付费模型");}
    e.Result=File.ReadAllText(args[2]);
   }finally{
    lock(gate){if(active!=null){active.Dispose();active=null;}}
    try{using(var cleanup=Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" unregister --name "+name){UseShellExecute=false,CreateNoWindow=true})){cleanup.WaitForExit(3000);}}catch{}
   }
  }
  void ShowResult(string raw,bool saved=false){
   var result=Json.Deserialize<VocabularyResult>(raw);if(!String.IsNullOrEmpty(result.error))throw new InvalidOperationException(result.error);lastJson=raw;
   ((DataGrid)View.FindName("Words")).ItemsSource=result.groups??result.words;((TextBox)View.FindName("FullText")).Text=result.task=="vision"?result.text:(result.readingText??result.text);
   if(result.task=="vision"){
    var details=new StringBuilder("\n\n图形元素（模型原答，未经核验）\n");var names=new Dictionary<string,string>();
    if(result.elements!=null)foreach(var node in result.elements){string id=Field(node,"id"),label=Field(node,"label");names[id]=label;details.AppendLine(id+" · "+label+"\n  依据："+Field(node,"evidence"));}
    details.AppendLine("\n关系记录（未经核验）");
    if(result.visualRelations!=null)foreach(var edge in result.visualRelations){string a=Field(edge,"source"),b=Field(edge,"target");details.AppendLine((names.ContainsKey(a)?names[a]:a)+" → "+(names.ContainsKey(b)?names[b]:b)+" · "+Field(edge,"type")+"\n  依据："+Field(edge,"evidence")+"；推断："+Field(edge,"inferred"));}
    ((TextBox)View.FindName("FullText")).AppendText(details.ToString());
   }
   ((TextBox)View.FindName("RawText")).Text=result.rawAnswer??result.text??raw;
   string scoring=result.task=="vision"?"图形评分：待GPT对照标准逐条核对，不使用文字召回冒充图形准确率。":"文字评分："+(result.benchmark==null?"待核对":Json.Serialize(result.benchmark));
   if(CurrentCase!=null){string gold=result.task=="vision"?CurrentCase.visionGold:CurrentCase.ocrGold;if(!String.IsNullOrEmpty(gold)&&File.Exists(gold))scoring+="\n\n标准答案：\n"+File.ReadAllText(gold);}
   ((TextBox)View.FindName("Scoring")).Text=scoring;((TabControl)View.FindName("AnswerTabs")).SelectedIndex=1;
   ((TextBlock)View.FindName("ResultMeta")).Text=ModelLabel(result.model)+(result.task=="vision"?" · 图形与结构":" · OCR");((TextBlock)View.FindName("ResultMeta")).ToolTip=result.model;
   string tokens=result.usage!=null&&result.usage.ContainsKey("total_tokens")?" · "+Convert.ToString(result.usage["total_tokens"])+" tokens":"";
   ((TextBlock)View.FindName("ResultStats")).Text=(result.groups==null?"":result.groups.Count+" 行组 · ")+(result.words==null?0:result.words.Count)+" 原始项 · "+result.elapsedSeconds.ToString("0.00")+" 秒"+tokens+(result.cached||saved?" · 已保存结果":"");
   ((Button)View.FindName("CopyResult")).IsEnabled=true;Status("完成 · 结果未经人工验证，点击词条查看原图位置");
   if(SystemParameters.ClientAreaAnimation)((DataGrid)View.FindName("Words")).BeginAnimation(UIElement.OpacityProperty,new DoubleAnimation(.35,1,TimeSpan.FromMilliseconds(160)));
   View.Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded,new Action(()=>{if(View.IsVisible){var table=(DataGrid)View.FindName("Words");table.BringIntoView(new Rect(0,0,Math.Max(1,table.ActualWidth),Math.Min(160,Math.Max(1,table.ActualHeight))));}}));
  }
  void Highlight(){
   var canvas=(Canvas)View.FindName("Markers");canvas.Children.Clear();var word=((DataGrid)View.FindName("Words")).SelectedItem as VocabularyWord;if(word==null)return;if(word.bbox==null||word.bbox.Length!=4){Status("当前词条没有位置数据，无法在原图定位");return;}
   var rect=new Rectangle{Width=word.bbox[2]*width/1000,Height=word.bbox[3]*height/1000,Stroke=new SolidColorBrush(Color.FromRgb(40,126,236)),StrokeThickness=Math.Max(2,width/500.0),Fill=new SolidColorBrush(Color.FromArgb(35,40,126,236))};Canvas.SetLeft(rect,word.bbox[0]*width/1000);Canvas.SetTop(rect,word.bbox[1]*height/1000);canvas.Children.Add(rect);
  }
  static string Field(Dictionary<string,object> row,string key){object value;return row.TryGetValue(key,out value)?Convert.ToString(value):"未提供";}
  void RecordInterrupted(string reason){
   if(String.IsNullOrEmpty(currentRequest)||!File.Exists(currentRequest))return;
   string output=System.IO.Path.Combine(System.IO.Path.GetDirectoryName(currentRequest),"result.json");if(File.Exists(output))return;
   AudioControls.Save(output,new Dictionary<string,object>{{"error",reason},{"cancelled",cancelled}});
   try{using(var finalize=Process.Start(new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name Visual-Finalize-"+Guid.NewGuid().ToString("N").Substring(0,8)+" --desc \"实验中断记录\" -- \""+AudioControls.Python(runtime())+"\" \""+System.IO.Path.Combine(AudioControls.CodeRoot(runtime()),"visual_experiment.py")+"\" --finalize \""+currentRequest+"\""+AudioControls.RootArgument(runtime())){UseShellExecute=false,CreateNoWindow=true})){finalize.WaitForExit(5000);}}catch{}
  }
  void Kill(){
   // Only the process tree created and held by this test instance is eligible.
   lock(gate){if(active==null||active.HasExited)return;
    using(var killer=Process.Start(new ProcessStartInfo("taskkill.exe","/PID "+active.Id+" /T /F"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true})){killer.WaitForExit(3000);}
    if(!active.WaitForExit(3000))throw new InvalidOperationException("测试进程尚未退出，请等待本次请求结束");
   }
  }
  void Cancel(){cancelled=true;Status("正在取消本次测试");Kill();}
  public void Open(){closed=false;RefreshSuite();SetBusy(worker.IsBusy);if(cancelled&&!worker.IsBusy)Status("已取消 · 可再次提取");}
  public void Close(){closed=true;if(worker.IsBusy){cancelled=true;Kill();}}
 }
}
