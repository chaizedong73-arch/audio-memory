using System;
using System.IO;
using System.Net;
using System.Text;
using System.Diagnostics;
using System.Collections.Generic;
using System.ComponentModel;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace AiAudioMemory {
 public sealed class SceneCameraPane {
  readonly string package,root;readonly JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=4*1024*1024};
  readonly DispatcherTimer timer=new DispatcherTimer();readonly BackgroundWorker reader=new BackgroundWorker(),action=new BackgroundWorker();
  readonly Image preview=new Image{Stretch=Stretch.Uniform,MaxHeight=430};readonly TextBlock state=new TextBlock{Text="尚未启动手机接收",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,12,0,10)};
  readonly TextBox answer=new TextBox{IsReadOnly=true,TextWrapping=TextWrapping.Wrap,AcceptsReturn=true,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,MinHeight=100,MaxHeight=240,FontSize=14,Text="截图后可提取板书文字，或手动选择Mini分析现场。"};
  readonly Button start=new Button{Content="启动手机接收"},usb=new Button{Content="USB连接手机"},wifi=new Button{Content="Wi-Fi连接手机"},record=new Button{Content="开始录像"},snap=new Button{Content="截图保存"},stop=new Button{Content="结束采集"};
  readonly Expander wifiPanel=new Expander{Header="Wi-Fi配对 · 首次安装证书，然后扫码连接",Visibility=Visibility.Collapsed,Margin=new Thickness(0,8,0,16)};
  readonly Image certificateQr=new Image{Width=200,Height=200},captureQr=new Image{Width=200,Height=200};readonly TextBlock wifiHelp=new TextBlock{TextWrapping=TextWrapping.Wrap,FontSize=14,LineHeight=22};string pairingSignature="";
  readonly TextBlock slideStatus=new TextBlock{Text="PPT自动定位：亮度初筛、本地small文字核对；可在手机手动框选。",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,8,0,12)};
  readonly ComboBox model=new ComboBox{MinWidth=220,Margin=new Thickness(0,0,10,0)};string frame="",notice="";DateTime noticeUntil;double frameAt;bool opened;
  public FrameworkElement View {get;private set;}
  public SceneCameraPane(string package,string root){
   this.package=package;this.root=root;
   var panel=new StackPanel{Margin=new Thickness(22,18,22,18)};panel.SetValue(TextElement.FontWeightProperty,FontWeights.Normal);View=new ScrollViewer{Content=panel,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
   panel.Children.Add(new TextBlock{Text="手机 · 现场采集",FontSize=22,FontWeight=FontWeights.SemiBold});
   panel.Children.Add(new TextBlock{Text="USB或同一局域网连接安卓手机，拍摄黑板、投影或桌面。资料保存在录音项目中。",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,8,0,18)});
   var row=new WrapPanel();foreach(var button in new[]{start,usb,wifi,record,snap,stop}){button.Margin=new Thickness(0,0,8,8);row.Children.Add(button);}panel.Children.Add(row);panel.Children.Add(state);
   var pairing=new StackPanel();pairing.Children.Add(wifiHelp);var qrRow=new WrapPanel();var first=new StackPanel{Margin=new Thickness(0,10,22,10)};first.Children.Add(new TextBlock{Text="1 · 下载项目CA证书"});first.Children.Add(certificateQr);qrRow.Children.Add(first);var second=new StackPanel{Margin=new Thickness(0,10,0,10)};second.Children.Add(new TextBlock{Text="2 · 安装后扫码连接"});second.Children.Add(captureQr);qrRow.Children.Add(second);pairing.Children.Add(qrRow);var allowLan=new Button{Content="手机打不开？允许本次局域网连接",HorizontalAlignment=HorizontalAlignment.Left,Margin=new Thickness(0,4,0,10)};pairing.Children.Add(allowLan);allowLan.Click+=(s,e)=>Run(()=>{var status=Call("/status");var settings=status["wifi"] as Dictionary<string,object>;if(settings==null)throw new Exception("请先生成Wi-Fi入口");var runtime=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Runtime));var info=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,"scene","allow-lan.ps1")+"\" -OwnerPid "+Convert.ToString(runtime["pid"])+" -Address "+Convert.ToString(settings["ip"])){UseShellExecute=true,Verb="runas",WindowStyle=ProcessWindowStyle.Hidden};Process.Start(info);return "请确认Windows授权；仅临时允许本地子网访问两个采集端口，结束采集后自动撤销";});wifiPanel.Content=pairing;panel.Children.Add(wifiPanel);
   panel.Children.Add(slideStatus);var openSlides=new Button{Content="查看PPT关键帧",HorizontalAlignment=HorizontalAlignment.Left,Margin=new Thickness(0,0,0,10)};panel.Children.Add(openSlides);openSlides.Click+=(s,e)=>{string folder=Path.Combine(root,"out","scene","ppt");Directory.CreateDirectory(folder);Process.Start(new ProcessStartInfo(folder){UseShellExecute=true});};
   var box=new Border{Background=new SolidColorBrush(Color.FromRgb(18,21,29)),CornerRadius=new CornerRadius(14),MinHeight=220,Child=preview,Margin=new Thickness(0,0,0,18)};panel.Children.Add(box);
   var analysisRow=new WrapPanel();model.Items.Add("本地 small · 提取板书文字");model.Items.Add("云端 2.0 Mini · 分析现场（计费）");model.SelectedIndex=0;analysisRow.Children.Add(model);
   var analyze=new Button{Content="分析当前画面"};analysisRow.Children.Add(analyze);panel.Children.Add(analysisRow);panel.Children.Add(answer);
   panel.Children.Add(new TextBlock{Text="退出工具箱或结束上课模式会关闭采集。手机切到后台也会停止摄像头。云端分析只在点击后发送当前画面。",FontSize=12,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,12,0,0)});
   start.Click+=(s,e)=>Run(()=>{if(!AudioControls.Classroom(root))throw new Exception("请先开启上课模式");if(File.Exists(Runtime)){try{Call("/status");return "手机接收已经运行";}catch{}}Launch("scene_capture.py","", "Scene-Camera-Receiver",false);return "接收服务启动中，请稍候";});
   usb.Click+=(s,e)=>Run(()=>{if(!File.Exists(Runtime))throw new Exception("请先启动手机接收");return Launch("scene_usb.py","","Scene-USB-Connect",true);});
   wifi.Click+=(s,e)=>Run(()=>{Call("/wifi",new{});return "Wi-Fi入口已生成，请展开配对说明；首次需手机安装项目CA证书";});
   record.Click+=(s,e)=>Run(()=>{var status=Call("/status");Call("/command",new{name=Convert.ToBoolean(status["recording"])?"preview":"record"});return "录像状态已请求，等待手机确认";});
   snap.Click+=(s,e)=>Run(()=>{var response=Call("/command",new{name="snapshot"});return "截图已保存："+Convert.ToString(response["result"]);});
   stop.Click+=(s,e)=>Run(()=>{Shutdown();return "已结束采集，摄像头与接收服务正在释放";});
   analyze.Click+=(s,e)=>{string id=model.SelectedIndex==0?"local:ppocr-v6-small":"doubao-seed-2-0-mini-260428";Run(()=>{Call("/analyze",new{model=id});return "正在分析当前画面，不会自动连续调用";});};
   reader.DoWork+=(s,e)=>{if(!File.Exists(Runtime)){e.Result=null;return;}e.Result=Call("/status");};
   reader.RunWorkerCompleted+=(s,e)=>{if(!opened)return;if(e.Error!=null){start.IsEnabled=true;usb.IsEnabled=record.IsEnabled=snap.IsEnabled=false;state.Text="接收服务未就绪，可重新启动："+e.Error.Message;return;}try{Apply(e.Result as Dictionary<string,object>);}catch(Exception error){state.Text="画面更新失败："+error.Message;}};
   action.DoWork+=(s,e)=>e.Result=((Func<string>)e.Argument)();action.RunWorkerCompleted+=(s,e)=>{if(opened){notice=e.Error==null?Convert.ToString(e.Result):e.Error.Message;noticeUntil=DateTime.Now.AddSeconds(25);state.Text=notice;}};
   timer.Interval=TimeSpan.FromSeconds(1);timer.Tick+=(s,e)=>{if(!AudioControls.Classroom(root)){Shutdown();return;}if(!reader.IsBusy)reader.RunWorkerAsync();};Apply(null);
  }
  string Runtime {get{return Path.Combine(root,"out","scene","runtime.json");}}
  Dictionary<string,object> Call(string path,object body=null){
   var runtime=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Runtime));string currentToken=Convert.ToString(runtime["token"]);
   var request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:19643"+path);request.Proxy=null;request.Timeout=path=="/wifi"?30000:2500;request.Headers["Authorization"]="Bearer "+currentToken;
   if(body!=null){request.Method="POST";request.ContentType="application/json";var bytes=Encoding.UTF8.GetBytes(json.Serialize(body));request.ContentLength=bytes.Length;using(var stream=request.GetRequestStream())stream.Write(bytes,0,bytes.Length);}
   try{using(var response=request.GetResponse())using(var reader=new StreamReader(response.GetResponseStream()))return json.Deserialize<Dictionary<string,object>>(reader.ReadToEnd());}
   catch(WebException ex){if(ex.Response!=null)using(var response=ex.Response)using(var r=new StreamReader(response.GetResponseStream())){var error=json.Deserialize<Dictionary<string,object>>(r.ReadToEnd());throw new Exception(Convert.ToString(error["error"]));}throw;}
  }
  string Launch(string script,string args,string name,bool wait){
   string registry=Path.Combine(AudioControls.ToolboxRoot(package),"registry.mjs");var info=new ProcessStartInfo("node.exe","\""+registry+"\" run --owner chatgpt --name "+name+" --desc \"手机现场采集\" -- \""+AudioControls.Python(root)+"\" \""+Path.Combine(root,script)+"\" "+args){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root,RedirectStandardOutput=wait,RedirectStandardError=wait,StandardOutputEncoding=wait?Encoding.UTF8:null};
   info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
   var process=Process.Start(info);if(!wait){process.Dispose();return "已启动";}
   using(process){if(!process.WaitForExit(30000))throw new Exception("USB操作仍未完成，请检查手机授权后重试");string output=process.StandardOutput.ReadToEnd();if(process.ExitCode!=0)throw new Exception(output+process.StandardError.ReadToEnd());return output;}
  }
  void Run(Func<string> work){if(action.IsBusy){state.Text="上一项操作仍在进行";return;}action.RunWorkerAsync(work);}
  void Apply(Dictionary<string,object> status){
   bool active=status!=null;start.IsEnabled=!active;usb.IsEnabled=wifi.IsEnabled=active;stop.IsEnabled=active;record.IsEnabled=snap.IsEnabled=active&&Convert.ToBoolean(status["connected"]);
   if(!active){state.Text=DateTime.Now<noticeUntil?notice:"尚未启动手机接收；启动后选择USB或Wi-Fi连接。";record.Content="开始录像";preview.Source=null;frame="";wifiPanel.Visibility=Visibility.Collapsed;pairingSignature="";return;}
   object wifiValue;if(status.TryGetValue("wifi",out wifiValue)&&wifiValue is Dictionary<string,object>){var settings=(Dictionary<string,object>)wifiValue;wifiPanel.Visibility=Visibility.Visible;string signature=Convert.ToString(settings["url"]);if(signature!=pairingSignature){certificateQr.Source=ReadImage(Convert.ToString(settings["certificateQr"]));captureQr.Source=ReadImage(Convert.ToString(settings["captureQr"]));wifiHelp.Text="手机与电脑连接同一Wi-Fi。先扫码下载camera-ca.cer，再在安卓设置中搜索CA证书并安装，名称为AI Recording Camera Local CA；安装前核对证书SHA256与下方一致，然后扫描第二个码，点击开启摄像头。此证书会成为手机信任的CA，测试结束可从用户凭据删除；私钥只保存在本项目。\n电脑地址："+Convert.ToString(settings["ip"])+"\n证书SHA256："+Convert.ToString(settings["fingerprint"])+"\n若手机打不开页面，请检查Windows网络访问提示、防火墙及Wi-Fi设备隔离。无需关闭整个防火墙。";wifiPanel.IsExpanded=true;pairingSignature=signature;}}
   object pptValue;if(status.TryGetValue("ppt",out pptValue)){var ppt=pptValue as Dictionary<string,object>;if(ppt!=null){object mode,autoValue;string message=Convert.ToString(ppt["message"]);if(ppt.TryGetValue("mode",out mode)&&Convert.ToString(mode)=="auto"&&ppt.TryGetValue("auto",out autoValue)&&autoValue is Dictionary<string,object>){var local=(Dictionary<string,object>)autoValue;message=Convert.ToString(local["message"])+" · 本地OCR "+Convert.ToString(local["ocrCalls"])+"次";}slideStatus.Text="PPT已提取 "+Convert.ToString(ppt["count"])+" 张 · "+message;}}
   bool recording=Convert.ToBoolean(status["recording"]);record.Content=recording?"停止录像":"开始录像";
   string delay=status["delaySeconds"]==null?"—":Convert.ToString(status["delaySeconds"])+"秒";
   state.Text=(Convert.ToBoolean(status["connected"])?(recording?"录像中":"手机已连接 · 预览中"):"等待手机：USB连接，或使用Wi-Fi配对二维码")+" · 画面延迟 "+delay+"\n"+Convert.ToString(status["error"])+(DateTime.Now<noticeUntil?"\n"+notice:"");
   var receipt=status["receipt"] as Dictionary<string,object>;if(receipt!=null&&Convert.ToString(receipt["state"])!="recording")state.Text+="\n录像："+Convert.ToString(receipt["state"])+" · "+Convert.ToString(receipt["path"]);
   string path=Convert.ToString(status["frame"]);double at=Convert.ToDouble(status["frameAt"]);if(path.Length>0&&File.Exists(path)&&(path!=frame||at!=frameAt)){var bitmap=new BitmapImage();using(var file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.StreamSource=file;bitmap.EndInit();bitmap.Freeze();}preview.Source=bitmap;frame=path;frameAt=at;}
   var result=status["analysis"] as Dictionary<string,object>;if(result!=null){object value;answer.Text=result.TryGetValue("text",out value)?Convert.ToString(value):result.TryGetValue("error",out value)?Convert.ToString(value):"分析中…";}
  }
  void Shutdown(){if(File.Exists(Runtime))try{Call("/command",new{name="disconnect"});}catch{} }
  static BitmapImage ReadImage(string path){var bitmap=new BitmapImage();using(var file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.StreamSource=file;bitmap.EndInit();bitmap.Freeze();}return bitmap;}
  public void Open(){opened=true;timer.Start();}
  public void Close(){opened=false;timer.Stop();Shutdown();}
 }
}
