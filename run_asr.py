# -*- coding: utf-8 -*-
"""本地转录探针 v2：PyAV 手动解码 + faster-whisper，绕开 av 版本兼容问题。

用法:
    python run_asr.py <音频> <模型> [起始秒] [时长秒]
"""
import os, sys, time, json

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import av
import numpy as np
from faster_whisper import WhisperModel

SR = 16000


def load_audio(path, sr=SR):
    """解码任意音视频为 16k 单声道 float32 numpy（PyAV 直解，不调 ffmpeg.exe）。"""
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
        chunks = []
        for frame in container.decode(stream):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray())
        for rf in resampler.resample(None):
            chunks.append(rf.to_ndarray())
    if not chunks:
        raise RuntimeError(f"解码失败或没有音频流: {path}")
    return np.concatenate(chunks, axis=1).flatten().astype(np.float32)


def main():
    audio_path = sys.argv[1]
    size = sys.argv[2] if len(sys.argv) > 2 else "small"
    t_clip = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    dur = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0

    t0 = time.time()
    audio = load_audio(audio_path)
    total = len(audio) / SR
    a = int(t_clip * SR)
    b = min(len(audio), int((t_clip + dur) * SR))
    clip = audio[a:b]
    print(f"[audio] 全长 {total:.1f}s，取 [{t_clip:.0f}, {t_clip+dur:.0f}] = {len(clip)/SR:.1f}s，"
          f"解码 {time.time()-t0:.1f}s", flush=True)

    t_load = time.time()
    model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=8)
    print(f"[load] {size} 用时 {time.time()-t_load:.1f}s", flush=True)

    t1 = time.time()
    segments, info = model.transcribe(
        clip,
        language="zh",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=True,
        initial_prompt="以下是一段中文口语录音，可能包含STM32、嵌入式、字幕等术语。",
    )
    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
        })
    t_run = time.time() - t1
    span = len(clip) / SR

    print(f"[info] 语言={info.language} 置信={info.language_probability:.2f}")
    print(f"[perf] 转写 {t_run:.1f}s / 音频 {span:.0f}s → RTF = {t_run/span:.3f}")
    print(f"[perf] 12 小时音频预计 {t_run/span*12:.1f} 小时")
    print(f"[out] {len(segs)} 段")
    for s in segs:
        print(f"  [{s['start']:7.2f}-{s['end']:7.2f}] {s['text']}")

    out = os.path.splitext(audio_path)[0] + f"_asr_{size}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": size, "start": t_clip, "seconds": span,
                   "runtime": t_run, "rtf": t_run / span,
                   "segments": segs}, f, ensure_ascii=False, indent=1)
    print(f"[saved] {out}")


if __name__ == "__main__":
    main()
