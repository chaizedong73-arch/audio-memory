# -*- coding: utf-8 -*-
"""流式录音 → 静默触发转写（准实时，边说边出字）

用法:
    python live.py                          # 默认：静默 30s 触发，最长 10 分钟强制切
    python live.py --max-seg 300            # 每 5 分钟强制切
    python live.py --max-seg 30             # 极限：每 30 秒切一段
    python live.py --device 14 --list       # 先看设备

触发规则（两条取先到者）:
    1. 连续 SILENCE_CHECKS 次检查都没人说话（默认 2 × 15s = 30s 静默）
    2. 当前段超过 --max-seg 秒

架构:
    录音线程 → queue → 主循环(VAD 判定/切段) → 转写队列 → 转写 worker
    转写是后台串行，不阻塞录音；RTF 0.27 意味着转写比录音快 3.7 倍
"""
from data_location import data_root as default_data_root
import os, sys, json, time, queue, threading, argparse, datetime, subprocess
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np
import sounddevice as sd
from faster_whisper.vad import VadOptions, get_speech_timestamps

SR = 16000
BLOCK = 1600          # 0.1 秒
HERE = os.path.dirname(os.path.abspath(__file__))
_HOT = json.load(open(os.path.join(HERE, "hotwords.json"), encoding="utf-8"))
PROMPT = _HOT["initial_prompt"]
REPL = _HOT["replacements"]
_CC = None


def postproc(t):
    global _CC
    if _CC is None:
        from opencc import OpenCC
        _CC = OpenCC("t2s")
    t = _CC.convert(t)
    for a, b in REPL:
        t = t.replace(a, b)
    return t


def speech_seconds(audio):
    """这段音频里有多少秒是真人在说话。"""
    if len(audio) == 0:
        return 0.0
    ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    return sum(x["end"] - x["start"] for x in ts) / SR


class Live:
    def __init__(self, args):
        self.args = args
        self.q = queue.Queue()
        self.tq = queue.Queue()
        self.stop = threading.Event()
        self.blocks_sec = BLOCK / SR
        self.check_sec = args.check
        self.buf = []
        self.buf_start = 0.0        # 当前段起点（秒，相对录音开始）
        self.total = 0.0            # 已录总时长
        self.since_check = 0.0
        self.silent_streak = 0
        self.feed_done = False
        self.n_seg = 0
        self.t0_wall = datetime.datetime.now()
        self.out = os.path.join(args.out, "timeline.jsonl")
        os.makedirs(args.out, exist_ok=True)
        self.lock = threading.Lock()

    # ---------- 录音 ----------
    def record_loop(self):
        if self.args.source:
            self.file_loop()
            return

        def cb(indata, frames, t, status):
            self.q.put(indata[:, 0].copy())
        with sd.InputStream(samplerate=SR, blocksize=BLOCK, channels=1,
                            dtype="float32", device=self.args.device, callback=cb):
            print(f"[rec] 开始录音（设备 {self.args.device}）Ctrl+C 结束", flush=True)
            while not self.stop.is_set():
                time.sleep(0.2)

    def file_loop(self):
        """把音频文件当麦克风喂进来，用于精确测实时性与分段逻辑。"""
        import av
        src = self.args.source
        with av.open(src) as c:
            st = c.streams.audio[0]
            rs = av.AudioResampler(format="fltp", layout="mono", rate=SR)
            chunks = []
            for fr in c.decode(st):
                for rf in rs.resample(fr):
                    chunks.append(rf.to_ndarray().flatten())
            for rf in rs.resample(None):
                chunks.append(rf.to_ndarray().flatten())
        audio = np.concatenate(chunks).astype(np.float32)
        n = len(audio)
        print(f"[src] {os.path.basename(src)} {n/SR:.1f}s "
              f"{'（实时速度）' if self.args.realtime else '（全速压测）'}", flush=True)
        i = 0
        t_start = time.time()
        while i < n and not self.stop.is_set():
            self.q.put(audio[i:i + BLOCK])
            i += BLOCK
            if self.args.realtime:
                target = t_start + i / SR
                wait = target - time.time()
                if wait > 0:
                    time.sleep(wait)
        self.feed_done = True
        print("[src] 素材喂完，等待转写队列排空", flush=True)

    # ---------- 定时抽取 ----------
    def extract_loop(self):
        """每隔 --extract-every 秒调一次 extract_memory.py（增量）。"""
        script = os.path.join(HERE, "extract_memory.py")
        py = sys.executable
        while not self.stop.is_set():
            for _ in range(int(self.args.extract_every)):
                if self.stop.is_set():
                    return
                time.sleep(1)
            print(f"\n[extract] 触发增量抽取（{self.fmt(self.total)} 处）", flush=True)
            try:
                p = subprocess.run([py, script, self.args.out,
                                    "--minutes", str(self.args.extract_minutes)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=900,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in (p.stdout or "").strip().splitlines():
                    print(f"  {line}", flush=True)
                if p.returncode != 0:
                    print(f"  [extract err] {p.stderr[:300]}", flush=True)
            except Exception as e:
                print(f"  [extract fail] {e!r}", flush=True)

    # ---------- 转写 ----------
    def transcribe_loop(self, model):
        while True:
            item = self.tq.get()
            if item is None:
                break
            audio, seg_start, seg_end = item
            t = time.time()
            try:
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
                    rows.append({
                        "start": round(seg_start + s.start, 2),
                        "end": round(seg_start + s.end, 2),
                        "t": (self.t0_wall + datetime.timedelta(seconds=seg_start + s.start)).strftime("%H:%M:%S"),
                        "text": txt,
                    })
                with self.lock:
                    with open(self.out, "a", encoding="utf-8") as f:
                        for r in rows:
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                el = time.time() - t
                backlog = self.tq.qsize()
                warn = f"  ⚠积压 {backlog}" if backlog >= 3 else ""
                print(f"\n[转写] {self.fmt(seg_start)}-{self.fmt(seg_end)} "
                      f"({seg_end-seg_start:.0f}s 音频 / {el:.1f}s){warn} → {len(rows)} 段", flush=True)
                for r in rows:
                    print(f"   {r['t']}  {r['text']}", flush=True)
            except Exception as e:
                print(f"[转写失败] {e!r}", flush=True)

    def fmt(self, sec):
        return f"{int(sec//60):02d}:{int(sec%60):02d}"

    # ---------- 切段 ----------
    def flush_segment(self, reason):
        if not self.buf:
            return
        audio = np.concatenate(self.buf)
        dur = len(audio) / SR
        self.buf = []
        start, end = self.buf_start, self.buf_start + dur
        self.buf_start = end
        if dur < self.args.min_seg:
            print(f"[skip] {self.fmt(start)}-{self.fmt(end)} 太短 {dur:.1f}s（{reason}）", flush=True)
            return
        speech = speech_seconds(audio)
        if speech < 1.0:                 # 整段几乎没人声：直接丢，不浪费转写
            print(f"[skip] {self.fmt(start)}-{self.fmt(end)} 几乎无人声 {speech:.1f}s（{reason}）", flush=True)
            return
        self.n_seg += 1
        print(f"[切段] #{self.n_seg} {self.fmt(start)}-{self.fmt(end)} "
              f"长度 {dur:.0f}s 人声 {speech:.0f}s 触发={reason}", flush=True)
        self.tq.put((audio, start, end))

    # ---------- 主循环 ----------
    def run(self):
        from faster_whisper import WhisperModel
        t = time.time()
        model = WhisperModel(self.args.model, device="cpu", compute_type="int8",
                             cpu_threads=self.args.threads)
        print(f"[model] {self.args.model} 加载 {time.time()-t:.1f}s（{self.args.threads} 线程）", flush=True)

        th_t = threading.Thread(target=self.transcribe_loop, args=(model,), daemon=True)
        th_t.start()
        th_x = None
        if self.args.extract_every > 0:
            th_x = threading.Thread(target=self.extract_loop, daemon=True)
            th_x.start()
            print(f"[extract] 每 {self.args.extract_every}s 自动抽记忆（每块 {self.args.extract_minutes} 分钟）",
                  flush=True)
        th_r = threading.Thread(target=self.record_loop, daemon=True)
        th_r.start()
        time.sleep(0.5)

        try:
            while not self.stop.is_set():
                try:
                    chunk = self.q.get(timeout=0.3)
                except queue.Empty:
                    if self.feed_done:
                        break
                    continue
                self.buf.append(chunk)
                self.total += len(chunk) / SR
                self.since_check += len(chunk) / SR

                if self.since_check >= self.check_sec:
                    self.since_check = 0.0
                    need = int(self.check_sec * SR)
                    win_chunks, tot = [], 0
                    for b in reversed(self.buf):
                        win_chunks.append(b)
                        tot += len(b)
                        if tot >= need:
                            break
                    win = np.concatenate(win_chunks[::-1])[-need:]
                    sp = speech_seconds(win)
                    seg_len = sum(len(b) for b in self.buf) / SR
                    mark = "有人" if sp > 0.5 else "静默"
                    print(f"[vad] {self.fmt(self.total)} 近{self.check_sec:.0f}s人声 {sp:.1f}s → {mark}"
                          f" | 当前段 {seg_len:.0f}s | 静默连击 {self.silent_streak}", flush=True)

                    if sp <= 0.5:
                        self.silent_streak += 1
                    else:
                        self.silent_streak = 0

                    if self.silent_streak >= self.args.silence_checks:
                        self.flush_segment(f"静默{self.silent_streak * self.check_sec:.0f}s")
                        self.silent_streak = 0

                    if seg_len >= self.args.max_seg:
                        self.flush_segment(f"达上限{self.args.max_seg}s")
                        self.silent_streak = 0
            # 素材/录音结束后把最后一段收掉
            self.flush_segment("结束")
            self.tq.put(None)          # 哨兵：让转写 worker 收尾
            th_t.join(timeout=1800)    # 等它把队列里的段全部转完
            print(f"[done] 共切 {self.n_seg} 段", flush=True)
        except KeyboardInterrupt:
            print("\n[stop] 收尾…", flush=True)
            self.stop.set()
            self.flush_segment("退出")
            self.tq.put(None)
            th_t.join(timeout=1800)
            print(f"[done] 共切 {self.n_seg} 段，输出 {self.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--model", default="small")
    ap.add_argument("--check", type=float, default=15.0, help="每隔多少秒做一次 VAD 判定")
    ap.add_argument("--silence-checks", type=int, default=2, help="连续几次静默就切段")
    ap.add_argument("--max-seg", type=float, default=600.0, help="单段最长秒数（强制切）")
    ap.add_argument("--min-seg", type=float, default=5.0, help="太短的段丢弃")
    ap.add_argument("--out", default=os.path.join(str(default_data_root()), "out", "live"))
    ap.add_argument("--source", default=None, help="用音频文件模拟麦克风")
    ap.add_argument("--realtime", action="store_true", help="按 1x 速度喂（默认全速压测）")
    ap.add_argument("--extract-every", type=float, default=600.0,
                    help="每隔多少秒抽一次记忆（0=关闭），默认 600")
    ap.add_argument("--extract-minutes", type=int, default=10,
                    help="抽取时按多少分钟一块")
    ap.add_argument("--threads", type=int, default=8,
                    help="whisper CPU 线程数。机器忙时降到 4-6，内存/竞争都小")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(sd.query_devices())
        return

    Live(args).run()


if __name__ == "__main__":
    main()
