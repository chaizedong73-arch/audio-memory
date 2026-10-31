# -*- coding: utf-8 -*-
"""两个刁钻场景的实测：同时说话 / 快速交替，diarization 到底能分出什么。

做法：拿官方 4 人样本里的两段不同说话人音频，人工合成两种情形，
再看模型输出与真值的偏差。合成音频不是真实对话，但能暴露算法边界。
"""
import os, sys, wave
import numpy as np
import sherpa_onnx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SEG = os.path.join(HERE, "models", "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
EMB = os.path.join(HERE, "models", "3dspeaker.onnx")
SR = 16000


def read_wav(p):
    with wave.open(p, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def diar(a, n=2, th=0.5):
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=SEG),
            num_threads=2),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMB, num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=n, threshold=th),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    return [(s.start, s.end, s.speaker) for s in sd.process(a).sort_by_start_time()]


def norm(x):
    return x / (np.abs(x).max() + 1e-9)


def save(p, a):
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def main():
    a, sr = read_wav(os.path.join(HERE, "models", "test4.wav"))
    A = a[int(0.3 * SR):int(5.0 * SR)]     # 说话人 0
    B = a[int(7.1 * SR):int(12.5 * SR)]    # 说话人 1
    n = min(len(A), len(B))
    A, B = A[:n], B[:n]
    print(f"素材 A {len(A)/SR:.1f}s  B {len(B)/SR:.1f}s\n")

    # ---- 场景一：两人完全重叠 ----
    mix = norm(norm(A) + 0.9 * norm(B))
    save(os.path.join(HERE, "_rectest", "ov_full.wav"), mix)
    print("=== 场景一：两人全程同时说话 ===")
    r = diar(mix, n=2)
    print(f"  输出 {len(r)} 段，涉及 {len({s for _,_,s in r})} 个说话人")
    tot = {}
    for st, en, sp in r:
        tot[sp] = tot.get(sp, 0) + (en - st)
    for k, v in sorted(tot.items()):
        print(f"    S{k}: {v:.1f}s ({v/sum(tot.values())*100:.0f}%)")

    # ---- 场景二：A 说 0.5s / B 说 0.5s 快速交替 ----
    chunk = int(0.5 * SR)
    parts, truth = [], []
    for i in range(0, (n // chunk) - 1, 2):
        parts.append(norm(A[i * chunk:(i + 1) * chunk]))
        truth.append("A")
        parts.append(norm(B[i * chunk:(i + 1) * chunk]))
        truth.append("B")
    alt = np.concatenate(parts)
    save(os.path.join(HERE, "_rectest", "ov_alt.wav"), alt)
    print(f"\n=== 场景二：0.5 秒一切、A/B 快速交替（共 {len(truth)} 句）===")
    r = diar(alt, n=2)
    print(f"  输出 {len(r)} 段，涉及 {len({s for _,_,s in r})} 个说话人")

    # 逐句看标签是否在 A/B 之间切换
    tags = []
    for i in range(len(truth)):
        st, en = i * 0.5, (i + 1) * 0.5
        best, ov = None, 0
        for s0, s1, sp in r:
            o = max(0, min(s1, en) - max(s0, st))
            if o > ov:
                best, ov = sp, o
        tags.append(best)
    print("  逐句标签:", "".join("?" if t is None else str(t) for t in tags))
    print("  真值    :", "".join("0" if t == "A" else "1" for t in truth))
    # 判断是否形成两簇：A 的标签集合与 B 的标签集合应尽量不相交
    sa = {t for t, g in zip(tags, truth) if g == "A" and t is not None}
    sb = {t for t, g in zip(tags, truth) if g == "B" and t is not None}
    print(f"  A 被标为 {sorted(sa)}，B 被标为 {sorted(sb)}")
    print(f"  → 能否分开：{'能' if sa and sb and not (sa & sb) else '不能（标签混了）'}")


if __name__ == "__main__":
    main()
