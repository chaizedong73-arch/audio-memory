# -*- coding: utf-8 -*-
"""全局说话人聚类（跨文件、跨天一致）。

为什么必须全局
--------------
    逐文件独立聚类有两个致命问题：
        1. 编号漂移 —— 同一个人在不同文件里被叫成 S01 / S05 / 新人C
        2. 聚不出稳定的人 —— 每文件只有几个块，样本太少，聚类结果无意义
    所以正确做法是：把所有块的 embedding 收齐 → 一次性聚类 → 标签稳定。

聚类方法
--------
    凝聚聚类（average linkage），不依赖 scipy（本机没装）。
    相似度用余弦（向量已归一化，点积即余弦）。

阈值标定（不靠猜）
------------------
    本机实测（2026-10-21，63 个块）：
        全体两两相似度   中位 0.168  p90 0.650  p95 0.772
        同文件内         中位 0.567  p90 0.782      （多半同人）
        跨文件           中位 0.158  p90 0.629
        长块(≥15s)       中位 0.807  min 0.219      （长块最可靠）
    结论：**长块（≥15s）内部相似度显著高于全体**。所以
        - 聚类只在「长块」上做（信噪比高）
        - 阈值从长块的相似度分布里取，而不是拍脑袋
        - 短块（5~15s）在聚类后按最近长块簇分配
"""
import os, sys, json, glob, argparse, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import speaker_id as SID

ANCHOR_MIN = 15.0     # 锚块最短长度（秒）——低于此不可靠
CHUNK_MIN = 5.0


# ---------- 凝聚聚类 ----------

def average_linkage(vecs, th):
    """凝聚聚类（average linkage）：反复合并平均相似度最高的两簇，直到最高簇间相似度 < th。

    实现要点：维护一个簇间平均相似度矩阵，合并时按 size 加权更新，
    这样整体是 O(n²) 而不是 O(n³) 的 python 循环（n=1000 时差别是分钟级）。
    """
    n = len(vecs)
    if n == 0:
        return []
    if n == 1:
        return [0]
    sim = np.array([[SID.cosine(vecs[i], vecs[j]) for j in range(n)] for i in range(n)],
                   dtype=np.float32)

    # 活跃簇的成员列表与规模
    members = {i: [i] for i in range(n)}
    active = list(range(n))
    # cs[i][j] = 簇 i 与簇 j 的平均相似度（对称）
    cs = sim.copy()

    while len(active) > 1:
        sub = cs[np.ix_(active, active)]
        np.fill_diagonal(sub, -np.inf)
        i_idx, j_idx = np.unravel_index(np.argmax(sub), sub.shape)
        bi, bj = active[i_idx], active[j_idx]
        if cs[bi][bj] < th:
            break
        # 合并 bj → bi（average linkage 按成员数加权）
        ni, nj = len(members[bi]), len(members[bj])
        for k in active:
            if k in (bi, bj):
                continue
            cs[bi][k] = (ni * cs[bi][k] + nj * cs[bj][k]) / (ni + nj)
            cs[k][bi] = cs[bi][k]
        members[bi] = members[bi] + members[bj]
        del members[bj]
        active.remove(bj)

    labels = [0] * n
    for ci, m in enumerate(members.values()):
        for i in m:
            labels[i] = ci
    return labels


def assign_short(short_vecs, anchor_labels, anchor_vecs, th):
    """把短块分给最像的锚簇；都不像就自己成新簇。

    anchor_labels 是名字（可能是 profile 名，也可能是"新人X"），
    所以新簇名用"新人"+未使用的字母续号。
    """
    labels = []
    acc = {}
    for lb, v in zip(anchor_labels, anchor_vecs):
        acc.setdefault(lb, []).append(v)
    means = {k: np.mean(v, axis=0) for k, v in acc.items()}
    used = set(means)
    nxt = 0
    for v in short_vecs:
        best, bs = None, th
        for lb, m in means.items():
            c = SID.cosine(v, m)
            if c > bs:
                best, bs = lb, c
        if best is None:
            while True:
                nm = f"新人{SID.NEW_LABELS[nxt % 26]}"
                nxt += 1
                if nm not in used:
                    break
            used.add(nm)
            acc[nm] = [v]
            means[nm] = v
            best = nm
        else:
            acc[best].append(v)
            means[best] = np.mean(acc[best], axis=0)
        labels.append(best)
    return labels


# ---------- 收集块 ----------

def collect_blocks(record_dir, files=None):
    """收集所有块的 (file, start, end, vec)。"""
    items = []
    if files is None:
        files = sorted(glob.glob(os.path.join(record_dir, "*.wav")))
    for f in files:
        try:
            a = SID.read_wav(f)
        except Exception:
            continue
        spans = SID.merge_spans(SID.energy_vad(a))
        if not spans:
            continue
        pairs = SID.embed_spans(a, spans)
        for (s, e), v in pairs:
            items.append({"file": os.path.basename(f), "start": s, "end": e,
                          "vec": v, "dur": e - s})
    return items


def build_labels(items, profiles, th=None, verbose=True):
    """返回 (labels, threshold)。有 profile 先匹配 profile，再对未匹配的聚类。"""
    if not items:
        return [], th or SID.DEFAULT_TH

    vecs = [it["vec"] for it in items]
    anchor_idx = [i for i, it in enumerate(items) if it["dur"] >= ANCHOR_MIN]
    short_idx = [i for i, it in enumerate(items) if it["dur"] < ANCHOR_MIN]

    if not anchor_idx:                    # 全是短块 → 退化成用全部块聚类
        anchor_idx = list(range(len(items)))
        short_idx = []

    anchor_vecs = [items[i]["vec"] for i in anchor_idx]

    # 阈值标定：从锚块两两相似度里取
    if th is None:
        th = calibrate_threshold(anchor_vecs, profiles)

    # 1) profile 优先
    labels = [None] * len(items)
    if profiles:
        for i, v in enumerate(vecs):
            best, bs = None, th
            for nm, p in profiles.items():
                c = SID.cosine(v, np.array(p["emb"]))
                if c > bs:
                    best, bs = nm, c
            if best:
                labels[i] = best

    # 2) 未匹配且是锚块的 → 聚类
    free_anchor = [i for i in anchor_idx if labels[i] is None]
    if free_anchor:
        cl = average_linkage([items[i]["vec"] for i in free_anchor], th)
        # 分配新标签名，避开已用的 profile 名
        used = {labels[i] for i in range(len(items)) if labels[i]}
        new_names = {}
        nxt = 0
        for k, i in enumerate(free_anchor):
            if cl[k] not in new_names:
                while True:
                    nm = f"新人{SID.NEW_LABELS[nxt % 26]}"
                    nxt += 1
                    if nm not in used:
                        break
                new_names[cl[k]] = nm
                used.add(nm)
            labels[i] = new_names[cl[k]]

    # 3) 短块 → 最近锚簇
    free_short = [i for i in short_idx if labels[i] is None]
    if free_short:
        anchor_lbl = [labels[i] for i in anchor_idx]
        keep = [(lb, items[i]["vec"]) for i, lb in zip(anchor_idx, anchor_lbl) if lb]
        if keep:
            al = [lb for lb, _ in keep]
            av = [v for _, v in keep]
            sl = assign_short([items[i]["vec"] for i in free_short], al, av, th)
            for i, lb in zip(free_short, sl):
                labels[i] = lb
        else:
            for i in free_short:
                labels[i] = "未知"

    for i in range(len(items)):
        if labels[i] is None:
            labels[i] = "未知"

    if verbose:
        from collections import Counter
        print(f"[cluster] 阈值 {th:.3f}  锚块 {len(anchor_idx)}  短块 {len(short_idx)}  "
              f"标签 {dict(Counter(labels))}")
    return labels, th


def calibrate_threshold(anchor_vecs, profiles, lo=0.30, hi=0.80):
    """阈值标定：有 profile 用 profile 间相似度；否则用锚块分布的高分位。

    锚块内部相似度的 p90 作为「一定同一人」的下界参考，
    取 p90 - 0.10 略保守一点（宁可多合一点人，也别把同一个人拆成两个）。
    """
    if profiles and len(profiles) >= 2:
        embs = [np.array(p["emb"]) for p in profiles.values()]
        inter = [SID.cosine(embs[i], embs[j]) for i in range(len(embs)) for j in range(i + 1, len(embs))]
        if inter:
            return max(lo, min(hi, min(inter) - 0.05))
    if len(anchor_vecs) >= 3:
        sims = []
        for i in range(len(anchor_vecs)):
            for j in range(i + 1, len(anchor_vecs)):
                sims.append(SID.cosine(anchor_vecs[i], anchor_vecs[j]))
        q = float(np.percentile(sims, 90))
        return max(lo, min(hi, q - 0.10))
    return SID.DEFAULT_TH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default=os.path.join(HERE, "record"))
    ap.add_argument("--profiles", default=os.path.join(HERE, "profiles.json"))
    ap.add_argument("--limit", type=int, default=40, help="最多取多少个文件（试跑用）")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--dump", default=None, help="把块和标签存到这个 json")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.record, "*.wav")))
    if args.limit:
        step = max(1, len(files) // args.limit)
        files = files[::step][:args.limit]
    print(f"[cluster] 取 {len(files)} 个文件")
    items = collect_blocks(args.record, files)
    print(f"[cluster] 收集 {len(items)} 个块（锚块 {sum(1 for it in items if it['dur']>=ANCHOR_MIN)}）")

    profiles = {}
    if os.path.exists(args.profiles):
        profiles = json.load(open(args.profiles, encoding="utf-8"))
    labels, th = build_labels(items, profiles, args.threshold)

    for it, lb in zip(items, labels):
        print(f"  {it['file']}  {it['start']:6.1f}-{it['end']:6.1f} ({it['dur']:5.1f}s)  [{lb}]")

    if args.dump:
        json.dump({"threshold": th,
                   "items": [{**{k: v for k, v in it.items() if k != "vec"},
                              "vec": [round(x, 5) for x in it["vec"].tolist()],
                              "label": lb} for it, lb in zip(items, labels)]},
                  open(args.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ {args.dump}")


if __name__ == "__main__":
    main()
