# -*- coding: utf-8 -*-
"""用 sounddevice 播放音频（PyAV 解码，绕开 ffmpeg.exe）。

用法: python play.py <音频> [秒数]
"""
import sys, av, numpy as np, sounddevice as sd

SR = 48000


def load(path, sr=SR):
    with av.open(path) as c:
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="fltp", layout="stereo", rate=sr)
        chunks = []
        for fr in c.decode(st):
            for rf in rs.resample(fr):
                chunks.append(rf.to_ndarray())
        for rf in rs.resample(None):
            chunks.append(rf.to_ndarray())
    a = np.concatenate(chunks, axis=1).T.astype(np.float32)  # (samples, channels)
    return a


def main():
    path = sys.argv[1]
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 70.0
    a = load(path)
    n = min(len(a), int(dur * SR))
    a = a[:n]
    print(f"[play] {n/SR:.1f}s of {len(a)/SR:.1f}s, peak={np.abs(a).max():.3f}", flush=True)
    sd.play(a, SR)
    sd.wait()
    print("[play] done", flush=True)


if __name__ == "__main__":
    main()
