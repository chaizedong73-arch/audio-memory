"""Extract stable slide images and repeated appearances from a local teaching video.

Uses the existing local detector; no model calls or audio uploads.

性能要点（2026-10-27 重写）：
1. 不再把每帧写成 JPEG 再读回来 —— ffmpeg 直接把 rawvideo 灌进管道，Python 只
   收 ndarray。省掉 2272 次 JPEG 编码 + 解码。
2. 优先走 d3d11va 硬解，并且把抽帧放在 hwdownload 之前，只有保留下来的那几帧才
   从显存搬回内存（实测 250 fps → 714 fps）。
3. 显著降维后的粗筛接管"是不是旧页"的判定，ECC 只在粗筛通过后才执行。
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from classroom_mode import save
from ppt_keyframes import SlideDetector

OUTPUT_WIDTH = 960
SAVE_WIDTH = 1920   # 保存图的宽度上限；源是 1080p 就按 1080p 存


def find_ffmpeg():
    candidate = os.environ.get('SLIDES_FFMPEG')
    if candidate:
        if Path(candidate).is_file(): return str(Path(candidate).resolve())
        raise RuntimeError('SLIDES_FFMPEG 指向的文件不存在：'+candidate)
    candidate = shutil.which('ffmpeg')
    if candidate: return candidate
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError('ffmpeg not found; set SLIDES_FFMPEG') from exc


def video_size(source, save_width=SAVE_WIDTH):
    """返回 (fps, 帧数, 时长, (保存宽, 高), (源宽, 源高))。
    保存尺寸默认取源分辨率，只在上限 SAVE_WIDTH 处截断——识别用的小图在 Python 侧缩，
    不再让 ffmpeg 把每一帧都缩一遍，省下的 swscale 正好抵掉大图多出来的管道字节。"""
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise ValueError('Cannot open video')
    fps = cap.get(cv2.CAP_PROP_FPS)
    count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    w0 = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    cap.release()
    if fps <= 0 or count <= 0 or height <= 0 or w0 <= 0:
        raise ValueError('Video duration/frame rate unavailable')
    nw, nh = int(w0), int(height)
    width = min(nw, int(save_width))
    if width % 2:
        width -= 1
    # 偶数宽高，避免 yuv420 缩放报错
    h = max(2, int(round(nh * width / nw / 2)) * 2)
    return fps, count, count / fps, (width, h), (nw, nh)


def frame_pipe(source, interval, width, height, limit, hardware, start=None, native=None):
    cmd = [find_ffmpeg(), '-hide_banner', '-loglevel', 'error']
    if hardware:
        cmd += ['-hwaccel', 'd3d11va', '-hwaccel_output_format', 'd3d11']
    if start:
        cmd += ['-ss', '%.3f' % start]
    cmd += ['-i', str(source)]
    if limit is not None:
        cmd += ['-t', '%.3f' % limit]
    # 尺寸与源一致时不做缩放：多一次 swscale 只会更慢（实测 522 → 406 fps）
    scale = '' if native is None or tuple(native) == (width, height) else ',scale=%d:%d' % (width, height)
    if hardware:
        # 先抽帧再下载：每秒只搬运 1 帧显存→内存，而不是 30 帧
        vf = 'fps=1/%g,hwdownload,format=nv12%s,format=bgr24' % (interval, scale)
    else:
        vf = 'fps=1/%g%s,format=bgr24' % (interval, scale)
    cmd += ['-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    # bufsize 只要一帧：给 8 帧的预读缓冲反而慢 2.6 倍（1080p 实测 34 → 88 ms/帧），
    # 因为每次 read 都会把整块缓冲搬一遍。
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=width * height * 3)


def read_frames(proc, width, height):
    size = width * height * 3
    stream = proc.stdout
    while True:
        buf = stream.read(size)
        if not buf:
            return
        while len(buf) < size:
            more = stream.read(size - len(buf))
            if not more:
                return
            buf += more
        yield np.frombuffer(buf, np.uint8).reshape(height, width, 3)


def frame_reader(proc, width, height, box):
    """解码等待与判定并行：读帧放在后台线程，主线程专心做检测。
    读一帧 16.6 ms、判定 19.2 ms，串行就是 36 ms；并行后取两者的较大值。"""
    try:
        for frame in read_frames(proc, width, height):
            box.put(frame)
    except Exception as exc:
        box.put(exc)
    finally:
        box.put(None)


def drain(proc, sink):
    try:
        for line in proc.stderr:
            sink.append(line.decode('utf-8', 'ignore').rstrip())
            if len(sink) > 40:
                del sink[0]
    except Exception:
        pass


def probe(source, interval, width, height, limit, hardware, native=None):
    """用前 3 秒试一把硬解：能正常出帧才敢拿整片去跑。"""
    trial = min(3.0, limit) if limit is not None else 3.0
    proc = frame_pipe(source, interval, width, height, trial, hardware, native=native)
    log = []
    thread = threading.Thread(target=drain, args=(proc, log), daemon=True)
    thread.start()
    got = 0
    try:
        for _ in read_frames(proc, width, height):
            got += 1
            if got >= 3:
                break
    finally:
        proc.stdout.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        thread.join(timeout=5)
        proc.stderr.close()
    return got >= 1, log


def extract(source, root, interval=1.0, roi=None, limit=None, hardware=True, save_width=SAVE_WIDTH, stop_file=None):
    if stop_file and Path(stop_file).exists(): raise InterruptedError('video extraction stopped')
    if interval <= 0:
        raise ValueError('interval must be positive')
    if limit is not None and limit <= 0:
        raise ValueError('limit must be positive')
    source = Path(source).resolve(strict=True)
    detector = SlideDetector(root)
    detector.configure(roi)
    fps, count, duration, (width, height), native = video_size(source, save_width)
    end = min(duration, limit) if limit is not None else duration
    started = time.monotonic()

    hw = hardware
    hw_note = 'software'
    if hw:
        ok, log = probe(source, interval, width, height, end, True, native)
        if ok:
            hw_note = 'd3d11va'
        else:
            hw = False
            hw_note = 'software (硬解探测失败: %s)' % (log[-1][:60] if log else '无帧')

    proc = frame_pipe(source, interval, width, height, end if limit is not None else None, hw, native=native)
    log = []
    thread = threading.Thread(target=drain, args=(proc, log), daemon=True)
    thread.start()
    box = queue.Queue(maxsize=3)
    reader = threading.Thread(target=frame_reader, args=(proc, width, height, box), daemon=True)
    reader.start()

    occurrences = []
    samples = 0
    last_page = None
    expected = max(1, int(end / interval))
    try:
        index = -1
        while True:
            if stop_file and Path(stop_file).exists():
                raise InterruptedError('video extraction stopped')
            try:
                frame = box.get(timeout=.2)
            except queue.Empty:
                continue
            if frame is None:
                break
            if isinstance(frame, Exception):
                raise frame
            index += 1
            position = index * interval
            if position >= end:
                break
            detector.feed_frame(frame, position)
            samples += 1
            # A changed candidate is unconfirmed until stability succeeds; do not
            # assign transition footage to the previously confirmed page.
            page = detector.current if detector.message in ('同页画面，不重复提取', '新页面已提取') else None
            if page != last_page:
                if occurrences and last_page is not None:
                    occurrences[-1]['endSeconds'] = position
                if page is not None:
                    start = detector.candidate_at
                    if occurrences:
                        occurrences[-1]['endSeconds'] = min(occurrences[-1]['endSeconds'], start)
                    occurrences.append({'pageId': page, 'startSeconds': start,
                                        'confirmedSeconds': position, 'endSeconds': min(position + interval, end)})
                last_page = page
            elif page is not None:
                occurrences[-1]['endSeconds'] = min(position + interval, end)
            if samples % 120 == 0:
                print(json.dumps({'seconds': position, 'duration': end, 'pages': len(detector.items),
                                  'elapsed': round(time.monotonic() - started, 1)}, ensure_ascii=False), flush=True)
    finally:
        if stop_file and Path(stop_file).exists() and proc.poll() is None:
            try: proc.terminate()
            except OSError: pass
            while True:
                try: box.get_nowait()
                except queue.Empty: break
        reader.join(timeout=5)
        proc.stdout.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        thread.join(timeout=5)
        proc.stderr.close()
    truncated = samples < expected - 2
    detector.persist()
    result = {'schemaVersion': 2, 'source': str(source), 'durationSeconds': duration,
              'processedSeconds': end, 'intervalSeconds': interval, 'roi': roi,
              'samples': samples, 'expectedSamples': expected, 'truncated': truncated,
              'frameSize': [width, height], 'sourceSize': list(native),
              'decode': hw_note, 'elapsedSeconds': round(time.monotonic()-started, 3),
              'uniquePages': len(detector.items), 'occurrences': occurrences,
              'index': str(detector.folder/'index.json'),
              'boundaryPrecision': 'sampled; stable confirmation, not exact slide cuts'}
    if truncated:
        print(json.dumps({'warning': '解码提前结束', 'samples': samples, 'expected': expected,
                          'stderr': log[-3:]}, ensure_ascii=False), flush=True)
    save(detector.folder/'video.json', result)
    contact_sheet(detector)
    timeline(detector, result)
    print(json.dumps({'output': str(detector.folder), **result}, ensure_ascii=False), flush=True)
    return result


def timeline(detector, result):
    now = datetime.now()
    lines = ['<!--@GPT '+now.strftime('%Y-%m-%dT%H:%M')+'-->',
             '# 教学视频关键帧', '',
             '源视频：'+result['source'], '',
             '下列为稳定画面提取结果，不是字幕或AI内容总结；时间边界为抽样估计。', '']
    for number, item in enumerate(detector.items, 1):
        ranges = [x for x in result['occurrences'] if x['pageId'] == item['id']]
        spans = '；'.join('%.1f–%.1f 秒' % (x['startSeconds'], x['endSeconds']) for x in ranges)
        lines.extend(['## %02d' % number, '', spans, '', '![]('+Path(item['path']).name+')', ''])
    lines.extend(['〔GPT·'+now.strftime('%m-%d %H:%M')+'〕', '<!--/@GPT-->'])
    (detector.folder/'关键帧时间线.md').write_text('\n'.join(lines), encoding='utf-8')


def contact_sheet(detector):
    items = detector.items
    for offset in range(0, len(items), 24):
        subset = items[offset:offset+24]
        sheet = Image.new('RGB', (1120, 180*((len(subset)+3)//4)), '#e8e8e8')
        draw = ImageDraw.Draw(sheet)
        for i, item in enumerate(subset):
            with Image.open(item['path']) as source:
                thumb = source.copy()
            thumb.thumbnail((274, 150))
            x, y = (i % 4)*280, (i//4)*180
            sheet.paste(thumb, (x, y))
            draw.text((x+4, y+153), '%04d  %.1fs' % (offset+i+1, item['firstSeenAt']), fill='black')
        sheet.save(detector.folder/('contact-%03d.jpg' % (offset//24+1)))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--roi', type=float, nargs=4, metavar=('X', 'Y', 'W', 'H'))
    p.add_argument('--limit', type=float, help='Explicit preview length in seconds; omit for full video')
    p.add_argument('--no-hw', action='store_true', help='禁用硬件解码，强制软件解码')
    p.add_argument('--save-width', type=int, default=SAVE_WIDTH, help='保存图宽度上限，默认按源分辨率')
    args = p.parse_args()
    extract(args.source, args.root, args.interval, args.roi, args.limit, not args.no_hw, args.save_width)
