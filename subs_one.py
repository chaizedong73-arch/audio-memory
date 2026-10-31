# -*- coding: utf-8 -*-
"""给单个 wav 出字幕（srt + 带时间戳的 txt），用于人工核对分人结果。"""
import os, sys, wave
import numpy as np

# 本机环境变量里的代理已失效（会 502），走国内镜像 + 只用已缓存模型
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from faster_whisper import WhisperModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diar_test")
os.makedirs(OUT, exist_ok=True)


def read_wav(p):
    with wave.open(p, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def ts(sec, comma=False):
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    s, ms = int(sec % 60), int((sec % 1) * 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def main():
    p = sys.argv[1]
    name = os.path.splitext(os.path.basename(p))[0]
    a, sr = read_wav(p)
    print(f"{name}  {len(a)/sr:.1f}s  {sr}Hz")

    m = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)
    segs, info = m.transcribe(a, language="zh", beam_size=1, vad_filter=True,
                              vad_parameters=dict(min_silence_duration_ms=500,
                                                  speech_pad_ms=200),
                              condition_on_previous_text=False)
    rows = [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]

    txt = os.path.join(OUT, name + ".txt")
    srt = os.path.join(OUT, name + ".srt")
    with open(txt, "w", encoding="utf-8") as f:
        for st, en, t in rows:
            f.write(f"[{ts(st)} → {ts(en)}] {t}\n")
    with open(srt, "w", encoding="utf-8") as f:
        for i, (st, en, t) in enumerate(rows, 1):
            f.write(f"{i}\n{ts(st,True)} --> {ts(en,True)}\n{t}\n\n")

    print(f"共 {len(rows)} 句\n")
    for st, en, t in rows:
        print(f"  {ts(st)}  {t}")
    print(f"\n落盘: {txt}\n      {srt}")


if __name__ == "__main__":
    main()
