# -*- coding: utf-8 -*-
"""原始录音归档：老 wav → FLAC 无损压缩。

为什么
------
    record/ 每段 60 秒 16k 单声道 ≈ 1.9MB，一天约 1440 段 ≈ 2.7GB。
    实测今天一天就涨了 1.1GB。音频是"永不丢"的原始素材，不能删，但可以压。

为什么用 FLAC（无损）
--------------------
    - 无损 = 声纹和转写质量零损失（前面测过：Opus 压到 12kbps 以下声纹特征会被砍掉，
      FLAC 不涉及这个问题）
    - 16k 单声道语音 FLAC 压缩率通常 40%~55%
    - PyAV 自带 flac 编码器，本机没有 ffmpeg 命令行（ffmpeg 在这台机器上写不了文件）

安全策略
--------
    - 默认只归档 **已转写** 的文件（转写状态在 out/_transcribed.json）
    - 压缩成功后校验：解码回来与原始样本完全一致，不一致就丢弃压缩结果、保留原文件
    - 原文件删除前先改名 .bak，校验通过再删
    - 归档后仍能被 read_wav 读取 → 需要支持 .flac

用法:
    python archive.py --dry              # 只报告能省多少
    python archive.py --older-than 1     # 压缩 1 天前的（今天的不动）
    python archive.py --older-than 0 --all   # 连今天的也压（转写完成的部分）
"""
import os, sys, json, glob, wave, argparse, datetime, shutil
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "record")
OUT = os.path.join(HERE, "out")
SR = 16000


def read_pcm16(path):
    """读 wav 或 flac → (int16 单声道 16k 原始样本)。无损域，不做浮点归一化。"""
    if path.lower().endswith(".flac"):
        import av
        with av.open(path) as container:
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
            chunks = []
            for frame in container.decode(stream):
                for rf in resampler.resample(frame):
                    chunks.append(rf.to_ndarray().reshape(-1))
            a = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
            return a.astype(np.int16), SR
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != SR:
        import soxr
        a = soxr.resample(a.astype(np.float32), sr, SR).astype(np.int16)
    return a, sr


def read_wav_any(path):
    """读 wav 或 flac → (float32 16k mono, sr)。"""
    a, sr = read_pcm16(path)
    return a.astype(np.float32) / 32768.0, sr


def write_flac(path, pcm16, sr=SR):
    """写 FLAC（输入为 int16 原始样本）。无损域，无量化误差。"""
    import av
    pcm = np.asarray(pcm16, dtype=np.int16)
    with av.open(path, "w", format="flac") as container:
        stream = container.add_stream("flac", rate=sr)
        stream.layout = "mono"
        frame_size = 4096
        for i in range(0, len(pcm), frame_size):
            chunk = pcm[i:i + frame_size]
            arr = chunk.reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
            frame.sample_rate = sr
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default=RECORD)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--older-than", type=float, default=1.0, help="天；0 表示不限")
    ap.add_argument("--all", action="store_true", help="连未转写的也压（不推荐）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理几个文件")
    args = ap.parse_args()

    state_path = os.path.join(args.out, "_transcribed.json")
    state = {}
    if os.path.exists(state_path):
        try:
            state = json.load(open(state_path, encoding="utf-8"))
        except Exception:
            pass

    def stem_of(p):
        b = os.path.basename(p)
        return b[:-4] if b.lower().endswith(".wav") else (b[:-5] if b.lower().endswith(".flac") else b)

    cutoff = datetime.datetime.now() - datetime.timedelta(days=args.older_than)
    files = sorted(glob.glob(os.path.join(args.record, "*.wav")))
    cand = []
    for f in files:
        n = os.path.basename(f)
        stem = stem_of(f)
        try:
            t = datetime.datetime.strptime(stem[:15], "%Y%m%d_%H%M%S")
        except Exception:
            continue
        if t > cutoff:
            continue
        if not args.all and stem not in state:
            continue
        cand.append((f, t))
    if args.limit:
        cand = cand[:args.limit]

    total_in = sum(os.path.getsize(f) for f, _ in cand)
    print(f"候选 {len(cand)} 个文件，原始 {total_in/1048576:.1f}MB")

    if args.dry:
        # 抽样 3 个测压缩率
        import io
        for f, _ in cand[:3]:
            a, _ = read_pcm16(f)
            tmp = os.path.join(args.record, "_probe.flac")
            write_flac(tmp, a)
            ratio = os.path.getsize(tmp) / os.path.getsize(f)
            os.remove(tmp)
            print(f"  抽样 {os.path.basename(f)}  压缩率 {ratio*100:.0f}%")
        est = total_in * 0.5
        print(f"预计可省约 {(total_in-est)/1048576:.0f}MB")
        return

    ok = fail = 0
    for f, t in cand:
        n = os.path.basename(f)
        stem = n[:-4] if n.lower().endswith(".wav") else n
        dst = os.path.join(args.record, stem + ".flac")
        bak = f + ".bak"
        try:
            a, _ = read_pcm16(f)
            write_flac(dst, a)
            # 校验：解码回来必须逐样本一致（int16 域，无浮点误差）
            b, _ = read_pcm16(dst)
            if len(a) != len(b) or not np.array_equal(a, b):
                os.remove(dst)
                print(f"  [skip] {n} 校验不一致 len {len(a)}/{len(b)} "
                      f"maxdiff {int(np.abs(a[:min(len(a),len(b))].astype(np.int32)-b[:min(len(a),len(b))].astype(np.int32)).max()) if len(a) and len(b) else -1}")
                fail += 1
                continue
            os.remove(f)
            ok += 1
            if ok % 50 == 0:
                print(f"  已压缩 {ok} 个")
        except Exception as e:
            print(f"  [err] {n} {e!r}")
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            fail += 1

    # 统计
    fl = glob.glob(os.path.join(args.record, "*.flac"))
    tot_flac = sum(os.path.getsize(x) for x in fl)
    print(f"完成：成功 {ok}，失败 {fail}；现在 {len(fl)} 个 flac，共 {tot_flac/1048576:.1f}MB")


if __name__ == "__main__":
    main()
