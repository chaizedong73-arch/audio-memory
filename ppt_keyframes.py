"""Local slide-region stability and duplicate filtering; never invokes OCR or an API."""
import io,time,uuid,hashlib
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from classroom_mode import save

class SlideDetector:
 COARSE_GATE=True
 # 识别只用 480 宽的缩图（1080p 直接缩到 320 要多花 3.4 ms，先缩到 480 再缩 320 只要 2.6 ms）；
 # 只有真要存页时才用原始分辨率编码。
 ANALYSIS_WIDTH=480
 PNG_COMPRESSION=3
 def __init__(self,root):
  self.root=Path(root);self.run=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
  self.folder=self.root/'out/scene/ppt'/self.run;self.roi=None;self.items=[];self.features=[]
  self.candidate=None;self.candidate_at=0;self.samples=0;self.current=None;self.message='等待稳定画面';self.last_seen_write=0
  self._coarse_mat=None;self.current_index=None;self.candidate_page=None
 def configure(self,roi):
  if roi is not None:
   if not isinstance(roi,list) or len(roi)!=4 or any(type(x) not in (float,int) or not np.isfinite(x) for x in roi):raise ValueError('PPT区域格式无效')
   x,y,w,h=roi
   if min(x,y)<0 or min(w,h)<.1 or x+w>1.001 or y+h>1.001:raise ValueError('请框选至少画面宽高10%的有效PPT区域')
  if roi==self.roi:return
  self.roi=roi;self.candidate=None;self.current=None;self.current_index=None;self.candidate_page=None;self.message='区域已更新，等待画面稳定'
  # Different regions are different observations. Never silently compare incompatible crops.
  self.features=[];self._coarse_mat=None;self.persist()
 def persist(self):
  self.folder.mkdir(parents=True,exist_ok=True)
  save(self.folder/'index.json',{'schemaVersion':1,'run':self.run,'roi':self.roi,'items':self.items,'algorithm':'local-slide-stability-1'})
 def status(self):
  return {'count':len(self.items),'message':self.message,'roi':self.roi,'latest':self.items[-1]['path'] if self.items else '',
   'directory':str(self.folder),'current':self.current}
 @staticmethod
 def signature(image):
  gray=cv2.cvtColor(np.array(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
  gray=cv2.resize(gray,(320,200),interpolation=cv2.INTER_AREA)
  quality=float(cv2.Laplacian(gray,cv2.CV_32F).var())
  return cv2.GaussianBlur(gray,(3,3),0).astype(np.float32),quality
 @staticmethod
 def signature_array(bgr):
  """直接从解码器给的 BGR ndarray 取签名，绕开 PIL 与 JPEG 往返。"""
  gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
  gray=cv2.resize(gray,(320,200),interpolation=cv2.INTER_AREA)
  quality=float(cv2.Laplacian(gray,cv2.CV_32F).var())
  return cv2.GaussianBlur(gray,(3,3),0).astype(np.float32),quality
 @staticmethod
 def coarse(sig):
  """320x200 池化成 32x20。分辨率降 10 倍，用于 ECC 之前的快手淘汰。"""
  return cv2.resize(sig,(32,20),interpolation=cv2.INTER_AREA)
 @staticmethod
 def normalized(x):
  return np.clip((x-x.mean())/max(float(x.std()),8),-3,3)
 @staticmethod
 def same(a,b):
  # ECC 单次 4~7 ms，而判"这是不是旧页"要扫全部历史页。先比 32x20 池化图：
  # 明显不同立即返回 False（约 40 us），只有"看着像"才值得付 ECC 的钱。
  if SlideDetector.COARSE_GATE:
   gate=np.abs(SlideDetector.normalized(SlideDetector.coarse(a))-SlideDetector.normalized(SlideDetector.coarse(b)))
   fraction=float(np.mean(gate>.5));magnitude=float(gate.mean())
   if fraction>=.12 or magnitude>=.40:return False
   # 注意：这里曾试过"粗图几乎重合就直接判同"的快通道，实测会在
   # 只多一行/少一个高亮的相邻页上误合并（1600~2273 秒窗口丢 1 页），已撤掉。
  # Estimate only small translations: do not warp a new slide until it looks like an old one.
  transform=np.eye(2,3,dtype=np.float32)
  try:
   score,warp=cv2.findTransformECC(a/255.,b/255.,transform,cv2.MOTION_TRANSLATION,(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,25,.001))
   if score>.55 and abs(warp[0,2])<8 and abs(warp[1,2])<5:
    b=cv2.warpAffine(b,warp,(320,200),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REFLECT)
  except cv2.error:pass
  a=a[8:-8,10:-10];b=b[8:-8,10:-10]
  def norm(x):return np.clip((x-x.mean())/max(float(x.std()),8),-3,3)
  delta=np.abs(norm(a)-norm(b))
  return float(np.mean(delta>.5))<.035 and float(delta.mean())<.16
 def coarse_matrix(self):
  """所有历史页的 32x20 归一化指纹，堆成矩阵，供一次向量化粗筛。"""
  if self._coarse_mat is None:
   self._coarse_mat=(np.stack([SlideDetector.normalized(SlideDetector.coarse(f)).ravel() for f,_ in self.features])
                     if self.features else np.zeros((0,640),np.float32))
  return self._coarse_mat
 def eligible(self,sig):
  """粗筛：返回可能同页的历史下标，**按粗距离从近到远**。
  课堂 PPT 共用一个模板，光靠"像"会放行一大批页；先比最像的那页，
  一旦命中就停，避免每帧跑十几次 ECC。"""
  if not SlideDetector.COARSE_GATE:return list(range(len(self.features)))
  mat=self.coarse_matrix()
  if not len(mat):return []
  d=np.abs(mat-SlideDetector.normalized(SlideDetector.coarse(sig)).ravel())
  distance=d.mean(axis=1)
  ok=np.nonzero((np.mean(d>.5,axis=1)<.12)&(distance<.40))[0]
  return ok[np.argsort(distance[ok])]
 def candidates(self,sig):
  """把"当前正在看的那页"提到最前：绝大多数帧属同一页，命中即停。"""
  order=list(self.eligible(sig))
  if self.current_index is not None and self.current_index<len(self.features):
   order=[i for i in order if i!=self.current_index]
   order.insert(0,self.current_index)
  return order
 def feed(self,data,at=None):
  with Image.open(io.BytesIO(data)) as source:
   image=source.convert('RGB')
  return self.feed_image(image,at)
 def feed_image(self,image,at=None):
  """Accept decoded video frames without an intermediate PNG encode/decode."""
  at=time.time() if at is None else at
  image=image.convert('RGB')
  full_image=image
  if self.roi:
   x,y,w,h=self.roi;W,H=image.size;image=image.crop((int(x*W),int(y*H),int((x+w)*W),int((y+h)*H)))
  signature,quality=self.signature(image)
  if quality<4:
   self.candidate=None;self.message='画面过于模糊或缺少内容，暂不提取';return None
  if self.candidate is None or not self.same(self.candidate,signature):
   self.candidate=signature;self.candidate_at=at;self.samples=1;self.candidate_page=None;self.message='检测到变化，等待稳定';return None
  self.samples+=1
  if self.samples<3 or at-self.candidate_at<2:
   self.message='等待画面稳定';return None
  # 候选一分未变时，它属于哪一页是已知的：不必每帧再把历史页扫一遍。
  order=[self.candidate_page] if self.candidate_page is not None and self.candidate_page<len(self.features) else self.candidates(signature)
  for index in order:
   if self.candidate_page==index or self.same(self.features[index][0],signature):
    self.current=self.items[index]['id'];self.current_index=index;self.candidate_page=index
    self.items[index]['lastSeenAt']=at;self.message='同页画面，不重复提取'
    if at-self.last_seen_write>=60:self.persist();self.last_seen_write=at
    return None
  self.folder.mkdir(parents=True,exist_ok=True);file=self.folder/f'{len(self.items)+1:04d}.png';image.save(file)
  original=file
  if self.roi:
   sources=self.folder/'sources';sources.mkdir(exist_ok=True);original=sources/file.name;full_image.save(original)
  item={'id':uuid.uuid4().hex,'path':str(file),'firstSeenAt':self.candidate_at,'capturedAt':at,'lastSeenAt':at,
        'roi':self.roi,'width':image.width,'height':image.height,'contentHash':hashlib.sha256(file.read_bytes()).hexdigest(),'quality':quality,
        'sourcePath':str(original),'sourceHash':hashlib.sha256(original.read_bytes()).hexdigest()}
  self.features.append((signature,len(self.items)));self._coarse_mat=None;self.items.append(item);self.current=item['id'];self.current_index=len(self.items)-1;self.message='新页面已提取';self.persist();return item
 def feed_frame(self,bgr,at=None):
  """喂解码器直接给出的 BGR ndarray：判定全程走 numpy，只有真要存页时才编码 PNG。"""
  at=time.time() if at is None else at
  frame=bgr
  if self.roi:
   x,y,w,h=self.roi;H,W=frame.shape[:2]
   frame=frame[int(y*H):int((y+h)*H),int(x*W):int((x+w)*W)]
  if frame.size==0:return None
  analysis=frame
  if frame.shape[1]>SlideDetector.ANALYSIS_WIDTH:
   aw=SlideDetector.ANALYSIS_WIDTH;ah=max(2,int(round(frame.shape[0]*aw/frame.shape[1]/2))*2)
   analysis=cv2.resize(frame,(aw,ah),interpolation=cv2.INTER_AREA)
  signature,quality=self.signature_array(analysis)
  if quality<4:
   self.candidate=None;self.message='画面过于模糊或缺少内容，暂不提取';return None
  if self.candidate is None or not self.same(self.candidate,signature):
   self.candidate=signature;self.candidate_at=at;self.samples=1;self.candidate_page=None;self.message='检测到变化，等待稳定';return None
  self.samples+=1
  if self.samples<3 or at-self.candidate_at<2:
   self.message='等待画面稳定';return None
  # 候选一分未变时，它属于哪一页是已知的：不必每帧再把历史页扫一遍。
  order=[self.candidate_page] if self.candidate_page is not None and self.candidate_page<len(self.features) else self.candidates(signature)
  for index in order:
   if self.candidate_page==index or self.same(self.features[index][0],signature):
    self.current=self.items[index]['id'];self.current_index=index;self.candidate_page=index
    self.items[index]['lastSeenAt']=at;self.message='同页画面，不重复提取'
    if at-self.last_seen_write>=60:self.persist();self.last_seen_write=at
    return None
  self.folder.mkdir(parents=True,exist_ok=True);file=self.folder/f'{len(self.items)+1:04d}.png'
  # cv2.imwrite 在非 ASCII 路径上会静默失败，走 imencode+tofile
  ok,buffer=cv2.imencode('.png',frame,[cv2.IMWRITE_PNG_COMPRESSION,SlideDetector.PNG_COMPRESSION])
  if not ok:raise RuntimeError('页面编码失败')
  buffer.tofile(str(file))
  original=file
  if self.roi:
   sources=self.folder/'sources';sources.mkdir(exist_ok=True);original=sources/file.name
   ok,buffer=cv2.imencode('.png',bgr,[cv2.IMWRITE_PNG_COMPRESSION,SlideDetector.PNG_COMPRESSION])
   if not ok:raise RuntimeError('原图编码失败')
   buffer.tofile(str(original))
  item={'id':uuid.uuid4().hex,'path':str(file),'firstSeenAt':self.candidate_at,'capturedAt':at,'lastSeenAt':at,
        'roi':self.roi,'width':int(frame.shape[1]),'height':int(frame.shape[0]),'contentHash':hashlib.sha256(file.read_bytes()).hexdigest(),'quality':quality,
        'sourcePath':str(original),'sourceHash':hashlib.sha256(original.read_bytes()).hexdigest()}
  self.features.append((signature,len(self.items)));self._coarse_mat=None;self.items.append(item);self.current=item['id'];self.current_index=len(self.items)-1;self.message='新页面已提取';self.persist();return item
