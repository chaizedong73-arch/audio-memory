# -*- coding: utf-8 -*-
"""扫描录音文件 → 逐个转写 → 追加到「按天分目录」的时间线。内存不够就暂停，恢复后接着跑。

与 recorder 完全解耦：只读磁盘上的 wav，不碰录音进程。

用法:
    python transcriber.py --dir record --out out                 # 常驻
    python transcriber.py --dir record --out out --once         # 处理完现存文件就退出
    python transcriber.py --dir record --out out --once --backfill-days 2

设计要点（2026-10-21 修正）
---------------------------
    1. **状态全局、输出按天**。旧版把 _transcribed.json 放在 out/YYYYMMDD/ 里，
       每天新建输出目录 → 状态为空 → 昨天的录音被整个重转一遍（实测 21 日目录里
       435 行来自 20 日，纯重复浪费）。现在状态统一在 out/_transcribed.json，
       输出按录音文件自身日期落到 out/YYYYMMDD/timeline.jsonl。
    2. **时间轴 = 当天 00:00 起的秒数**（start/end），另附绝对时间戳 ts。
       旧版用「全局第一个文件」做基准，跨天后 start 能到 6 万秒，cursor 语义混乱。
    3. **失败可重试**。旧版把失败记成 -1 就永远不再处理。现在失败单独记在
       _fail.json 里，下一轮重试，连续失败 3 次才放弃。

行为:
    - 每 --poll 秒扫一次目录，按文件名时间排序
    - 可用内存低于 --min-mb 时进入等待，不抢占内存
    - 时间轴由文件名时间推算，不依赖写盘时间
"""
import os, sys, json, time, glob, argparse, datetime, ctypes, tempfile

import numpy as np
import wave
from faster_whisper import WhisperModel

SR = 16000
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "hotwords.json"), encoding="utf-8") as hotwords_file:
    _HOT = json.load(hotwords_file)
PROMPT = _HOT["initial_prompt"]
REPL = _HOT["replacements"]
_CC = None
MAX_FAIL = 3


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def avail_mb():
    if os.name != 'nt':
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.ullAvailPhys / (1024 * 1024)


def postproc(t):
    global _CC
    if _CC is None:
        from opencc import OpenCC
        _CC = OpenCC("t2s")
    t = _CC.convert(t)
    for a, b in REPL:
        t = t.replace(a, b)
    return t


def read_wav(path):
    """读 wav / flac 并统一到 16k 单声道。录音端可能写 48k（USB 接收器只支持 48k）。"""
    if path.lower().endswith(".flac"):
        import av
        with av.open(path) as container:
            stream = container.streams.audio[0]
            rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
            chunks = []
            for frame in container.decode(stream):
                for rf in rs.resample(frame):
                    chunks.append(rf.to_ndarray().reshape(-1))
            a = np.concatenate(chunks).astype(np.float32) / 32768.0 if chunks else np.zeros(0, np.float32)
        return a
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR:
        import soxr
        a = soxr.resample(a, sr, SR).astype(np.float32)
    return a


def parse_time(name):
    """20261020_143015_0001.wav → datetime"""
    d = name[:8]
    t = name[9:15]
    return datetime.datetime.strptime(d + t, "%Y%m%d%H%M%S")


def day_of(name):
    """文件名日期 → YYYYMMDD"""
    return name[:8]


def stem_of(path):
    """文件主名（去扩展名）。

    状态键用主名而不是全名：归档会把 xxx.wav 换成 xxx.flac，
    用全名做键会导致压缩过的文件被当成"没转过"再转一遍。
    """
    b = os.path.basename(path)
    return b[:-4] if b.lower().endswith(".wav") else (b[:-5] if b.lower().endswith(".flac") else b)


def day_zero(name):
    """该录音所属那天的 00:00"""
    return datetime.datetime.strptime(name[:8], "%Y%m%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "record"))
    ap.add_argument("--out", default=None, help="输出根目录（内部按天建 YYYYMMDD 子目录）")
    ap.add_argument("--model", default="base")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--poll", type=float, default=30.0, help="扫目录间隔秒数")
    ap.add_argument("--min-mb", type=float, default=600.0, help="可用内存低于此值就暂停")
    ap.add_argument("--once", action="store_true")
    ap.add_argument('--stop-file', default=None, help='停止信号文件，处理当前分片后退出')
    ap.add_argument("--backfill-days", type=int, default=3,
                    help="允许回补最近几天的录音（防止漏转后永远补不上）")
    args = ap.parse_args()

    outroot = args.out or os.path.join(os.path.dirname(os.path.abspath(args.dir)), "out")
    data_root = os.path.dirname(os.path.abspath(outroot))
    import singlelock
    _lk = singlelock.acquire(os.path.join(data_root, ".locks", "transcriber.lock"))
    if _lk is None:
        print("[tr] 已有 transcriber 在运行，退出。", flush=True)
        return

    os.makedirs(outroot, exist_ok=True)
    state_path = os.path.join(outroot, "_transcribed.json")
    fail_path = os.path.join(outroot, "_fail.json")

    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as state_file:
            state = json.load(state_file)
    fails = {}
    if os.path.exists(fail_path):
        with open(fail_path, encoding="utf-8") as fail_file:
            fails = json.load(fail_file)

    model = None
    print(f"[tran] 监听 {args.dir} → {outroot}  模型 {args.model}  {args.threads} 线程  "
          f"内存下限 {args.min_mb:.0f}MB", flush=True)

    def save_state():
        for path, value in ((state_path, state), (fail_path, fails)):
            fd, temporary = tempfile.mkstemp(prefix='.asr-state-', suffix='.tmp', dir=outroot)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    json.dump(value, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)

    def wait_or_stop(seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if args.stop_file and os.path.exists(args.stop_file):return True
            time.sleep(min(.2 if args.stop_file else seconds,max(0,deadline-time.monotonic())))
        return bool(args.stop_file and os.path.exists(args.stop_file))

    while True:
        if args.stop_file and os.path.exists(args.stop_file):return
        files = sorted(glob.glob(os.path.join(args.dir, "*.wav")) +
                       glob.glob(os.path.join(args.dir, "*.flac")))
        # 回补窗口之外的历史文件不处理（避免一次转几天）
        cutoff = None
        if args.backfill_days > 0:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=args.backfill_days)).strftime("%Y%m%d")
        todo = []
        for f in files:
            stem = stem_of(f)
            if stem in state:
                continue
            if cutoff and day_of(stem) < cutoff:
                continue
            todo.append(f)

        if not todo:
            if args.once:
                print("[tran] 没有待转文件", flush=True)
                return
            if wait_or_stop(args.poll):return
            continue

        for f in todo:
            if args.stop_file and os.path.exists(args.stop_file):return
            name = os.path.basename(f)
            stem = stem_of(f)
            free = avail_mb()
            if free < args.min_mb:
                print(f"[tran] 可用内存 {free:.0f}MB < {args.min_mb:.0f}MB，暂停等待…", flush=True)
                if args.once:
                    return
                if wait_or_stop(60):return
                break

            if model is None:
                t = time.time()
                local_model=os.path.join(HERE,'models','asr',args.model)
                selected_model=local_model if os.path.isfile(os.path.join(local_model,'model.bin')) else args.model
                model = WhisperModel(selected_model, device="cpu", compute_type="int8",
                                     cpu_threads=args.threads,download_root=os.path.join(HERE,'models','asr-cache'))
                print(f"[tran] 模型加载 {time.time()-t:.1f}s", flush=True)

            try:
                audio = read_wav(f)
                d0 = day_zero(stem)
                offset = (parse_time(stem) - d0).total_seconds()
                t = time.time()
                segments, _ = model.transcribe(
                    audio, language="zh", beam_size=1, vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
                    condition_on_previous_text=False, initial_prompt=PROMPT or None,
                )
                rows = []
                for s in segments:
                    txt = postproc(s.text.strip())
                    if not txt:
                        continue
                    abs_s = offset + s.start
                    rows.append({
                        "start": round(abs_s, 2),
                        "end": round(offset + s.end, 2),
                        "ts": (d0 + datetime.timedelta(seconds=abs_s)).timestamp(),
                        "t": (d0 + datetime.timedelta(seconds=abs_s)).strftime("%H:%M:%S"),
                        "date": d0.strftime("%Y-%m-%d"),
                        "file": stem,
                        "text": txt,
                    })
                daydir = os.path.join(outroot, day_of(stem))
                os.makedirs(daydir, exist_ok=True)
                with open(os.path.join(daydir, "timeline.jsonl"), "a", encoding="utf-8") as fo:
                    for r in rows:
                        fo.write(json.dumps(r, ensure_ascii=False) + "\n")
                state[stem] = len(rows)
                fails.pop(stem, None)
                save_state()
                try:
                    from classroom_materials import publish
                    publish(daydir, vault=os.path.join(outroot, 'live-materials'), root=data_root)
                except Exception as export_error:
                    # A note-export failure must not retry or duplicate transcription.
                    print(f"[classroom] export failed: {type(export_error).__name__}", flush=True)
                el = time.time() - t
                print(f"[tran] {name}  {len(audio)/SR:.0f}s → {el:.1f}s  {len(rows)} 段 "
                      f"(RTF {el/(len(audio)/SR):.2f})", flush=True)
            except Exception as e:
                print(f"[tran] {name} 失败: {e!r}", flush=True)
                fails[stem] = fails.get(stem, 0) + 1
                save_state()
                if fails[stem] >= MAX_FAIL:
                    print(f"[tran] {name} 连续失败 {fails[stem]} 次，放弃（内容留在 record/ 可手工重试）",
                          flush=True)
                    state[stem] = -1
                    save_state()

        if args.once:
            return
        if wait_or_stop(args.poll):return


if __name__ == "__main__":
    main()
