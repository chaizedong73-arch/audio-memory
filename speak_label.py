# -*- coding: utf-8 -*-
"""把「谁在说」贴到文字上：diarization 分段 + ASR 识别，按时间重叠合并。

流程（顺序不能换）：
    1. 声纹分离给出一串 [start, end, speaker]
    2. ASR 给出一串 [start, end, text]
    3. 每个 ASR 段按「与哪个 speaker 重叠最多」打标签
       —— 一段横跨两人时，标 mixed，不硬猜

用法:
    python speak_label.py 音频.wav                 # 默认 2 人
    python speak_label.py 音频.wav -n 4            # 指定 4 人
    python speak_label.py 音频.wav -n -1 -t 0.9    # 不指定人数，用阈值
"""
import os, sys, wave, argparse
import numpy as np
import sherpa_onnx

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from faster_whisper import WhisperModel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SEG = os.path.join(HERE, "models", "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
EMB = os.path.join(HERE, "models", "3dspeaker.onnx")
SR = 16000


def read_wav(path):
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


def diarize(a, n_clusters, threshold):
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=SEG),
            num_threads=2),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMB, num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=n_clusters, threshold=threshold),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    return [(s.start, s.end, s.speaker) for s in sd.process(a).sort_by_start_time()]


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("-t", type=float, default=0.5)
    ap.add_argument("--model", default="base")
    a = ap.parse_args()

    audio = read_wav(a.wav)
    dur = len(audio) / SR
    print(f"音频 {os.path.basename(a.wav)}  {dur:.1f}s\n")

    ds = diarize(audio, a.n, a.t)
    speakers = sorted({s for _, _, s in ds})
    print(f"分离结果：{len(speakers)} 人 / {len(ds)} 段")
    for st, en, sp in ds:
        print(f"  S{sp}  {st:6.2f}-{en:6.2f}  ({en-st:.1f}s)")

    print("\n转写中…")
    m = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=4)
    segs, _ = m.transcribe(audio, language="zh", beam_size=1, vad_filter=True,
                           condition_on_previous_text=False)

    print("\n=== 带说话人的文本 ===")
    for s in segs:
        txt = s.text.strip()
        if not txt:
            continue
        # 找重叠最多的 speaker
        best, best_ov = None, 0.0
        for st, en, sp in ds:
            ov = overlap(s.start, s.end, st, en)
            if ov > best_ov:
                best, best_ov = sp, ov
        seg_len = max(0.01, s.end - s.start)
        if best is None:
            tag = "??"
        elif best_ov / seg_len < 0.6:
            tag = f"S{best}+"          # 横跨多人，只标主要那个
        else:
            tag = f"S{best}"
        print(f"[{tag:4s}] {s.start:6.2f}-{s.end:6.2f}  {txt}")


if __name__ == "__main__":
    main()
