# -*- coding: utf-8 -*-
"""说话人识别：声纹注册(enroll) → 逐句标注(tag) → 阈值标定(calib)。

为什么需要它（2026-10-21 实测诊断）
----------------------------------
    - 3dspeaker.onnx 对 <2s 的段几乎不可靠。原先 diar 直接喂 1~2s 碎段，
      59.5s 音频判出 4 个人、编号 0/1/5/6 乱跳 —— 根因是段太碎，不是模型差。
      → 铁律：先 VAD 去掉静音，再把语音段合并到 ≥5s（上限 30s）再提 embedding。
    - DJI 降噪是硬噪声门，静音段 rms 精确为 0，提出来的 embedding 是废的。
      → 提声纹前必须 VAD。
    - 聚类出来的 S01/S02 编号每次重启都洗牌。→ 加 enrollment（注册）层：
      profile 优先匹配，认不出来的才聚类成"新人A/B"。

三条路线的关系（按性价比）
--------------------------
    A 分来源（loopback 拆出电脑放的音）→ B 目标说话人提取 TSE（只留你）
    → C 离线分离 + 注册辨认（= 本模块）→ D 端到端大模型（太重，本机吃力）
    A/B 做完之后 C 可能根本不需要；本模块是"兜底 + 可选增强"。

用法
----
    python speaker_id.py enroll 张三 record/xxx.wav [--more 另一段.wav ...]
    python speaker_id.py tag record/xxx.wav                    # 只看分段
    python speaker_id.py tag record/xxx.wav --timeline out/20261021/timeline.jsonl
    python speaker_id.py calib a.wav b.wav c.wav               # 给建议阈值
    python speaker_id.py auto out/20261021                      # 批量给整个目录打标

profiles 存 profiles.json；阈值默认 0.45，可用 --threshold 覆盖。
"""
import os, sys, json, wave, argparse, datetime, glob
import numpy as np
import sherpa_onnx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
EMB = os.path.join(HERE, "models", "3dspeaker.onnx")
PROFILES = os.path.join(HERE, "profiles.json")
SR = 16000
NEW_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

MIN_CHUNK = 5.0     # 提 embedding 的最短段（秒）——低于 3s 噪声太大
MAX_CHUNK = 30.0    # 太长会让 embedding 被多段内容平均掉
MERGE_GAP = 1.0     # 间隔小于此值就并成一段
DEFAULT_TH = 0.45


# ---------- 音频与 VAD ----------

def read_wav(path):
    """读 wav / flac → 16k 单声道 float32。"""
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


def energy_vad(a, hop_s=0.010, min_speech=0.3):
    """帧能量 VAD。DJI 归零静音 rms=0，用相对阈值即可分开。

    返回 [(start_s, end_s)] 语音区间；<min_speech 的碎段直接丢弃。
    """
    hop = int(SR * hop_s)
    n = len(a) // hop
    if n == 0:
        return []
    rms = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    if rms.max() <= 0:
        return []
    floor = max(np.percentile(rms, 95) * 0.05, 1e-4)
    speech = rms > floor
    spans, st = [], None
    for i, v in enumerate(speech):
        if v and st is None:
            st = i
        elif not v and st is not None:
            spans.append((st * hop_s, i * hop_s))
            st = None
    if st is not None:
        spans.append((st * hop_s, n * hop_s))
    return [(s, e) for s, e in spans if e - s >= min_speech]


def merge_spans(spans, gap=MERGE_GAP, max_len=MAX_CHUNK, min_len=MIN_CHUNK):
    """把语音段合并成适合提 embedding 的块。

    规则：
        1) 相邻段 gap < gap 并成一段
        2) 并到 >= min_len 才算一块；达不到 min_len 的尾巴并回上一块
        3) 超过 max_len 硬切
    """
    if not spans:
        return []
    merged, cs, ce = [], spans[0][0], spans[0][1]
    for s, e in spans[1:]:
        if s - ce < gap and e - cs < max_len:
            ce = e
        else:
            merged.append((cs, ce))
            cs, ce = s, e
    merged.append((cs, ce))

    out = []
    for s, e in merged:
        if out and (e - out[-1][0]) < min_len:
            ps, pe = out[-1]
            out[-1] = (ps, e)          # 短尾巴并回上一块
        else:
            out.append((s, e))
    # 仍短于 min_len 的整块：留，但会被标记为低置信（见 tag_file）
    return out


# ---------- 声纹 ----------

_EXT = None

def extractor():
    global _EXT
    if _EXT is None:
        _EXT = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMB, num_threads=2))
    return _EXT


def embed_one(audio):
    """提取一条声纹向量。

    注意 API：sherpa-onnx 1.13.8 的 SpeakerEmbeddingExtractor 没有 create_embedding，
    正确用法是 create_stream → accept_waveform(sample_rate, waveform) → input_finished
    → 等 is_ready → compute()。输出维度 512（不是 192）。
    """
    ext = extractor()
    s = ext.create_stream()
    s.accept_waveform(float(SR), np.asarray(audio, dtype=np.float32).tolist())
    s.input_finished()
    for _ in range(200):
        if ext.is_ready(s):
            break
        s.input_finished()
    v = np.asarray(ext.compute(s), dtype=np.float32)
    n = np.linalg.norm(v)
    if n > 0:
        v = v / n          # 归一化 → 余弦相似度就是点积
    return v


def embed_spans(a, spans):
    """返回 [(span, vec)]，只保留长度足够的段（<1s 的没有 embedding 价值）。"""
    out = []
    for s, e in spans:
        seg = a[int(s * SR):int(e * SR)]
        if len(seg) < SR:
            continue
        out.append(((s, e), embed_one(seg)))
    return out


def load_profiles():
    if os.path.exists(PROFILES):
        return json.load(open(PROFILES, encoding="utf-8"))
    return {}


def save_profiles(p):
    json.dump(p, open(PROFILES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def auto_threshold(vecs, profiles, floor=0.35, ceil=0.75):
    """自动阈值：优先用 profile 之间的相似度定界，没有 profile 用块间分布。

    规则：
        - 有 profile：阈值取 (最小 profile 间相似度 - 0.05)，夹在 [floor, ceil]
        - 无 profile：阈值取块两两相似度的 90 分位（同一说话人的块相似度更高）
    """
    if profiles:
        embs = [np.array(p["emb"]) for p in profiles.values()]
        inter = [cosine(embs[i], embs[j]) for i in range(len(embs)) for j in range(i + 1, len(embs))]
        if inter:
            return max(floor, min(ceil, min(inter) - 0.05))
    if len(vecs) >= 2:
        sims = [cosine(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
        q = float(np.percentile(sims, 90))
        return max(floor, min(ceil, q - 0.05))
    return DEFAULT_TH


# ---------- 标注核心 ----------

def label_chunks(vecs, profiles, th):
    """给每个块标名字：profile 优先，未命中的做贪心聚类成"新人X"。

    vecs: [(span, vector)] 或 [vector]
    """
    if vecs and isinstance(vecs[0], tuple):
        items = vecs
    else:
        items = [(None, v) for v in vecs]
    labels = [None] * len(items)
    names = list(profiles)
    for i, (_, v) in enumerate(items):
        best, bs = None, th
        for nm in names:
            c = cosine(v, np.array(profiles[nm]["emb"]))
            if c > bs:
                best, bs = nm, c
        if best:
            labels[i] = best

    clusters = []
    for i, (_, v) in enumerate(items):
        if labels[i]:
            continue
        hit = None
        for ci, cv in enumerate(clusters):
            if cosine(v, cv["mean"]) >= th:
                hit = ci
                break
        if hit is None:
            clusters.append({"mean": v.copy(), "idx": [i]})
        else:
            clusters[hit]["idx"].append(i)
            clusters[hit]["mean"] = np.mean([items[j][1] for j in clusters[hit]["idx"]], axis=0)
    for ci, c in enumerate(clusters):
        nm = f"新人{NEW_LABELS[ci % 26]}"
        for i in c["idx"]:
            labels[i] = nm
    return labels


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def tag_file(wav_path, segs, th=None, profiles=None, verbose=False):
    """给一个 wav 的若干句打说话人标签。

    segs: [(start_s, end_s)] 相对该 wav 起点的区间（whisper 的段）
    返回与 segs 等长的标签列表。
    """
    a = read_wav(wav_path)
    spans = merge_spans(energy_vad(a))
    if not spans:
        return ["未知"] * len(segs)
    pairs = embed_spans(a, spans)          # [(span, vec)]
    if not pairs:
        return ["未知"] * len(segs)
    vecs = [v for _, v in pairs]
    if profiles is None:
        profiles = load_profiles()
    if th is None:
        th = auto_threshold(vecs, profiles)
    labels = label_chunks(pairs, profiles, th)
    if verbose:
        print(f"  [spk] {os.path.basename(wav_path)} 块 {len(pairs)} 段，阈值 {th:.2f}，"
              f"标签 {sorted(set(labels))}")

    out = []
    for (ss, se) in segs:
        best, bo = "未知", 0.0
        # 注意：pairs 的元素是 ((start, end), vec)，labels 是并行列表。
        # 旧版写成 for ((s, e), lb) in zip(pairs, labels) —— 解包层级错了，
        # s 变成元组、e 变成向量数组，overlap() 里 min() 直接炸。
        for (span, lb) in zip(pairs, labels):
            s, e = span
            ov = overlap(ss, se, s, e)
            if ov > bo:
                best, bo = lb, ov
        out.append(best)
    return out


# ---------- CLI ----------

def wav_spans_vecs(path):
    a = read_wav(path)
    spans = merge_spans(energy_vad(a))
    pairs = embed_spans(a, spans)
    return a, spans, pairs


def cmd_enroll(args):
    """把一个(或多个)音频里某人的语音平均成一条 profile。"""
    vecs = []
    for path in args.wavs:
        _, spans, pairs = wav_spans_vecs(path)
        print(f"  {os.path.basename(path)}: {len(pairs)} 个有效段")
        vecs += [v for _, v in pairs]
    if not vecs:
        print("没有可用语音段，检查音频")
        return
    mean = np.mean(vecs, axis=0)
    profiles = load_profiles()
    old = profiles.get(args.name)
    if old:
        mean = (np.array(old["emb"]) * old["n"] + mean * len(vecs)) / (old["n"] + len(vecs))
        print(f"已存在 {args.name}（n={old['n']}），增量合并")
    profiles[args.name] = {
        "emb": [round(x, 5) for x in mean.tolist()],
        "n": (old["n"] if old else 0) + len(vecs),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_profiles(profiles)
    print(f"✅ {args.name} 已注册（累计 {profiles[args.name]['n']} 段）")


def cmd_tag(args):
    """对一个分片跑：profile 匹配 + 未匹配段聚类，可贴回 timeline。"""
    a, spans, pairs = wav_spans_vecs(args.wav)
    if not pairs:
        print("全片静音（或低于噪声门），无有效段")
        return
    profiles = load_profiles()
    vecs = [v for _, v in pairs]
    th = args.threshold or auto_threshold(vecs, profiles)
    labels = label_chunks(pairs, profiles, th)
    print(f"{os.path.basename(args.wav)}  有效语音 {spans[0][0]:.1f}-{spans[-1][1]:.1f}s，"
          f"{len(pairs)} 段（合并后）  阈值 {th:.2f}")
    for ((s, e), lb) in zip(pairs, labels):
        print(f"  [{lb:6s}] {s:6.2f}-{e:6.2f}  ({e-s:.1f}s)")

    if args.timeline:
        rows = [json.loads(l) for l in open(args.timeline, encoding="utf-8") if l.strip()]
        mine = [r for r in rows if r["file"] == os.path.basename(args.wav)]
        if not mine:
            print(f"timeline 里没有 {os.path.basename(args.wav)} 的记录")
            return
        day0 = datetime.datetime.strptime(os.path.basename(args.wav)[:8], "%Y%m%d")
        file_start = (datetime.datetime.strptime(
            os.path.basename(args.wav)[:15], "%Y%m%d_%H%M%S") - day0).total_seconds()
        rel = [(r["start"] - file_start, r["end"] - file_start) for r in mine]
        labs = tag_file(args.wav, rel, th=th, profiles=profiles)
        side = os.path.join(os.path.dirname(args.timeline), "speaker.jsonl")
        with open(side, "a", encoding="utf-8") as fo:
            for r, lb in zip(mine, labs):
                fo.write(json.dumps({"file": r["file"], "start": r["start"], "end": r["end"],
                                     "t": r.get("t"), "speaker": lb}, ensure_ascii=False) + "\n")
        print(f"✅ {len(mine)} 句已贴标签 → {side}")

    if args.timeline:
        rows = [json.loads(l) for l in open(args.timeline, encoding="utf-8") if l.strip()]
        mine = [r for r in rows if r["file"] == os.path.basename(args.wav)]
        if not mine:
            print(f"timeline 里没有 {os.path.basename(args.wav)} 的记录")
            return
        # 时间轴基准：timeline 的 start 现在是「当天 00:00 起的秒数」，
        # 而分片内的相对时间要换算成同一天的时间。
        base_day = None
        for r in mine:
            d = (r.get("file") or "")[:8]
            if len(d) == 8 and d.isdigit():
                base_day = datetime.datetime.strptime(d, "%Y%m%d")
                break
        if base_day is None:
            print("无法从文件名推断日期，无法对齐")
            return
        day0 = base_day.replace(hour=0, minute=0, second=0)
        segs, rs = [], []
        for r in mine:
            s = r["start"]
            e = r["end"]
            # start 是当天秒数；分片起点 = 文件名时间 - 当天 00:00
            segs.append((s, e))
            rs.append(r)
        file_start = (datetime.datetime.strptime(
            os.path.basename(args.wav)[:15], "%Y%m%d_%H%M%S") - day0).total_seconds()
        rel = [(s - file_start, e - file_start) for s, e in segs]
        labs = tag_file(args.wav, rel, th=th, profiles=profiles)
        out = 0
        for r, lb in zip(rs, labs):
            r["speaker"] = lb
            out += 1
        dst = args.timeline.replace(".jsonl", "") + ".speaker.jsonl"
        with open(dst, "w", encoding="utf-8") as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"✅ {out}/{len(mine)} 句已贴标签 → {dst}")


def cmd_calib(args):
    """同人/异人相似度分布 → 建议阈值。每份音频视为一个不同的人。"""
    vecs, who = [], []
    for path in args.wavs:
        _, spans, pairs = wav_spans_vecs(path)
        if not pairs:
            print(f"{os.path.basename(path)}: 无有效段，跳过")
            continue
        vecs.append(np.mean([v for _, v in pairs], axis=0))
        who.append(os.path.basename(path))
    same, diff = [], []
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            diff.append(cosine(vecs[i], vecs[j]))
    print(f"共 {len(vecs)} 份音频（视为不同人），异人对 {len(diff)} 个")
    if diff:
        print(f"异人相似度: min={min(diff):.3f}  中位={np.median(diff):.3f}  max={max(diff):.3f}")
        print(f"建议阈值 ≈ {max(0.35, min(diff) - 0.05):.2f}")
    for path in args.wavs:
        _, spans, pairs = wav_spans_vecs(path)
        vs = [v for _, v in pairs]
        inner = [cosine(vs[i], vs[j]) for i in range(len(vs)) for j in range(i + 1, len(vs))]
        if inner:
            print(f"  {os.path.basename(path)} 同人段 {len(inner)} 对: "
                  f"min={min(inner):.3f} 中位={np.median(inner):.3f} max={max(inner):.3f}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("enroll")
    p.add_argument("name")
    p.add_argument("wavs", nargs="+")
    p.set_defaults(fn=cmd_enroll)

    p = sub.add_parser("tag")
    p.add_argument("wav")
    p.add_argument("--timeline", default=None)
    p.add_argument("--threshold", type=float, default=None)
    p.set_defaults(fn=cmd_tag)

    p = sub.add_parser("calib")
    p.add_argument("wavs", nargs="+")
    p.set_defaults(fn=cmd_calib)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
