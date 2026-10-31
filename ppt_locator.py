"""Bright/rectangular screen proposals plus throttled local OCR confirmation."""
import io,json,time,uuid,threading
from pathlib import Path
import cv2,numpy as np
from PIL import Image
from classroom_mode import save
from ppt_keyframes import SlideDetector

def overlap(a,b):
 x=max(a[0],b[0]);y=max(a[1],b[1]);right=min(a[0]+a[2],b[0]+b[2]);bottom=min(a[1]+a[3],b[1]+b[3])
 inter=max(0,right-x)*max(0,bottom-y)
 return inter/max(1e-9,a[2]*a[3]+b[2]*b[3]-inter)

def proposals(image):
 rgb=np.asarray(image.convert('RGB'));H,W=rgb.shape[:2];scale=min(1,720/max(W,H))
 gray=cv2.cvtColor(cv2.resize(rgb,(round(W*scale),round(H*scale))),cv2.COLOR_RGB2GRAY);h,w=gray.shape
 smooth=cv2.GaussianBlur(gray,(5,5),0);level=max(120,min(220,float(np.percentile(smooth,75))+20))
 bright=cv2.morphologyEx((smooth>level).astype('uint8')*255,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
 edges=cv2.morphologyEx(cv2.Canny(smooth,40,120),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
 result=[]
 for mask,is_bright in [(bright,True),(edges,False)]:
  contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
  for contour in contours:
   x,y,bw,bh=cv2.boundingRect(contour);area=bw*bh/(w*h);ratio=bw/max(bh,1)
   if not(.06<=area<=.92 and 1.05<=ratio<=2.5 and bw>=w*.18 and bh>=h*.10):continue
   if cv2.contourArea(contour)/(bw*bh)<.65:continue
   if not is_bright:
    polygon=cv2.approxPolyDP(contour,cv2.arcLength(contour,True)*.025,True)
    if not 4<=len(polygon)<=6:continue
   region=gray[y:y+bh,x:x+bw];pad=max(4,min(bw,bh)//12)
   ox,oy=max(0,x-pad),max(0,y-pad);ex,ey=min(w,x+bw+pad),min(h,y+bh+pad)
   ring=gray[oy:ey,ox:ex];ring_mask=np.ones(ring.shape,dtype=bool);ring_mask[y-oy:y-oy+bh,x-ox:x-ox+bw]=False
   contrast=float(region.mean()-ring[ring_mask].mean()) if ring_mask.any() else 0
   if is_bright and contrast<6:continue
   if not is_bright and contrast<3 and np.percentile(region,95)<180:continue
   roi=[x/w,y/h,bw/w,bh/h]
   if any(overlap(roi,row['roi'])>.85 for row in result):continue
   result.append({'roi':roi,'brightness':round(float(region.mean()),2),'contrast':round(contrast,2),
                  'score':float(area**.5*(1+max(0,contrast)/80)),'source':'bright' if is_bright else 'rectangle'})
 return sorted(result,key=lambda row:row['score'],reverse=True)[:3]

def crop(image,roi):
 x,y,w,h=roi;W,H=image.size;return image.crop((int(x*W),int(y*H),int((x+w)*W),int((y+h)*H)))

def text_evidence(lines):
 good=[row for row in lines if float(row.get('score',0))>=.65 and len(''.join(c for c in row.get('text','') if c.isalnum()))>=2]
 chars=sum(sum(c.isalnum() for c in row['text']) for row in good)
 # Text is supporting evidence for a slide-like screen, not semantic proof that it is a PPT.
 return {'accepted':len(good)>=2 and chars>=12,'reliableLines':len(good),'characters':chars,'lines':lines}

class LocalSmallOcr:
 def __init__(self,root):self.root=Path(root);self.engine=None
 def __call__(self,file):
  if self.engine is None:
   from rapidocr import RapidOCR
   data=json.loads((self.root/'visual-models/catalog.json').read_text(encoding='utf-8-sig'))
   spec=next((r for r in data.get('catalog',[]) if r['id']=='local:ppocr-v6-small'),None)
   if not spec or not all(Path(spec[k]).is_file() for k in ('det','rec')):raise ValueError('本地small OCR资源缺失，未自动下载或切换云端')
   self.engine=RapidOCR(params={'Det.model_path':spec['det'],'Rec.model_path':spec['rec'],'Global.use_cls':False,
     'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':2})
  output=self.engine(str(file))
  if output.txts is None:return []
  return [{'text':str(text),'score':float(score)} for text,score in zip(output.txts,output.scores)]

class AutoPptLocator:
 def __init__(self,root,on_result,lock=None,ocr=None):
  self.root=Path(root);self.on_result=on_result;self.lock=lock or threading.RLock();self.ocr=ocr or LocalSmallOcr(root)
  self.generation=0;self.busy=False;self.closed=False;self.last_scan=-1e10;self.last_attempt=-1e10;self.pending=None;self.missing=0
  self.locked=None;self.message='自动定位：等待明亮矩形与文字证据';self.ocr_calls=0;self.cache=[]
 def reset(self):
  with self.lock:
   self.generation+=1;self.locked=None;self.pending=None;self.last_scan=-1e10;self.last_attempt=-1e10;self.missing=0;self.message='自动定位：等待课件区域'
 def close(self):
  with self.lock:self.closed=True;self.generation+=1
 def status(self):return {'message':self.message,'busy':self.busy,'roi':self.locked,'ocrCalls':self.ocr_calls,'method':'brightness-rectangle-local-ocr-1'}
 def feed(self,data,at=None):
  at=time.time() if at is None else at
  if self.closed or self.busy or at-self.last_scan<3:return
  self.last_scan=at
  with Image.open(io.BytesIO(data)) as source:image=source.convert('RGB')
  candidates=proposals(image)
  if self.locked:
   if any(overlap(row['roi'],self.locked)>.60 for row in candidates):self.missing=0;return
   self.missing+=1
   if self.missing<3:self.message='原区域暂时被遮挡，等待恢复';return
   self.locked=None;self.pending=None;self.message='画面位置改变，重新定位';self.on_result(None);return
  if not candidates:self.pending=None;self.message='未找到可靠的明亮矩形，可手动框选';return
  lead=candidates[0]['roi'];signature,_=SlideDetector.signature(crop(image,lead))
  if self.pending is None or overlap(lead,self.pending[0])<.75 or not SlideDetector.same(self.pending[1],signature):
   self.pending=(lead,signature);self.message='发现候选，等待画面稳定';return
  if at-self.last_attempt<10:return
  self.last_attempt=at;self.busy=True;generation=self.generation;self.message='正在用本地small核对文字'
  def work():
   folder=self.root/'out/scene/auto-ppt'/uuid.uuid4().hex
   attempts=[];found=None
   try:
    folder.mkdir(parents=True,exist_ok=True);image.save(folder/'source.png')
    for index,row in enumerate(candidates[:2]):
     with self.lock:
      if self.closed or generation!=self.generation:return
     part=crop(image,row['roi']);feature,_=SlideDetector.signature(part)
     match=next((entry for entry in self.cache if SlideDetector.same(entry['signature'],feature)),None)
     if match and (match['evidence']['accepted'] or at-match['time']<60):evidence=dict(match['evidence'],cached=True,sourceEvidence=match['path'])
     else:
      file=folder/f'candidate-{index+1}.png';part.save(file)
      with self.lock:self.ocr_calls+=1
      started=time.perf_counter();evidence=text_evidence(self.ocr(file));evidence['elapsedSeconds']=round(time.perf_counter()-started,3)
      self.cache.append({'signature':feature,'evidence':evidence,'time':at,'path':str(folder/'result.json')});self.cache=self.cache[-12:]
     attempts.append({**row,'ocr':evidence})
     if evidence['accepted']:found=row['roi'];break
    save(folder/'result.json',{'method':'brightness-rectangle-local-ocr-1','frameAt':at,'attempts':attempts,'acceptedRoi':found,'verification':'heuristic'})
    with self.lock:
     if self.closed or generation!=self.generation:return
     if found:self.locked=found;self.missing=0;self.message='已定位疑似课件区域（本地OCR支持）';self.on_result(found)
     else:self.message='候选文字证据不足，稍后复查或手动框选'
   except Exception as error:
    with self.lock:
     if generation==self.generation:self.message='自动定位未完成：'+str(error)[:180]
    try:save(folder/'error.json',{'error':str(error)[:800]})
    except OSError:pass
   finally:
    with self.lock:self.busy=False
  threading.Thread(target=work,daemon=True).start()
