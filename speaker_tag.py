# -*- coding: utf-8 -*-
"""第四层：给时间线打说话人标签 → 写侧车文件 speaker.jsonl。

为什么是侧车文件而不是直接改 timeline.jsonl
------------------------------------------
    timeline.jsonl 由 transcriber 持续追加。抽取器/打标器若原地改写它，
    会和转写进程抢同一个文件（丢行、写半行）。侧车文件独立、只追加，天然安全。

流程
----
    timeline.jsonl ──┐
                     ├─→ speaker.jsonl   （本脚本）
    record/*.wav ────┘
    profiles.json  ──┘   （注册声纹，可选；没有就聚类成"新人A/B"）

段长规则（实测诊断后的硬约束）
-----------------------------
    3dspeaker.onnx 对 <2s 的段几乎不可靠（1~2s 段喂进去等于噪声）。
    所以：先 VAD 去静音 → 语音段合并到 ≥5s（上限 30s）→ 提 embedding →
    再用重叠把标签贴回 whisper 的句子。

用法:
    python speaker_tag.py --out out/20261021            # 给某天打标
    python speaker_tag.py --out out --all                # 给所有天打标
    python speaker_tag.py --out out/20261021 --force     # 重打
"""
import os, sys, json, glob, argparse, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import speaker_id as SID


def file_offset(fn):
    """文件起始时间 → 当天 00:00 起的秒数"""
    d0 = datetime.datetime.strptime(fn[:8], "%Y%m%d")
    t = datetime.datetime.strptime(fn[:15], "%Y%m%d_%H%M%S")
    return (t - d0).total_seconds()


def tag_day(daydir, record_dir, threshold=None, force=False, verbose=True):
    tl = os.path.join(daydir, "timeline.jsonl")
    side = os.path.join(daydir, "speaker.jsonl")
    if not os.path.exists(tl):
        return 0, 0
    rows = [json.loads(l) for l in open(tl, encoding="utf-8") if l.strip()]
    if not rows:
        return 0, 0

    done = set()
    if os.path.exists(side) and not force:
        for line in open(side, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["file"])
                except Exception:
                    pass

    profiles = SID.load_profiles()
    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    out = []
    n_new = 0
    for fn, rs in sorted(by_file.items()):
        if fn in done:
            continue
        # timeline.jsonl 里的 file 字段是「无扩展名 stem」（如 20261020_153820_0001），
        # 不是文件名。旧版在这里又切 4 字符当扩展名 → 路径全错、音频找不到。
        stem = fn
        base = fn
        wav = os.path.join(record_dir, stem + ".wav")
        if not os.path.exists(wav):
            wav = os.path.join(record_dir, stem + ".flac")   # 归档后是 flac
        if not os.path.exists(wav):
            continue
        fo = file_offset(fn)
        rel = [(r["start"] - fo, r["end"] - fo) for r in rs]
        try:
            labs = SID.tag_file(wav, rel, th=threshold, profiles=profiles, verbose=verbose)
        except Exception as e:
            print(f"[warn] {fn} 打标失败: {e!r}")
            continue
        for r, lb in zip(rs, labs):
            out.append({"file": fn, "start": r["start"], "end": r["end"],
                        "t": r.get("t"), "speaker": lb})
        n_new += len(rs)

    if out:
        with open(side, "a", encoding="utf-8") as fo2:
            for o in out:
                fo2.write(json.dumps(o, ensure_ascii=False) + "\n")
    return n_new, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--record", default=os.path.join(HERE, "record"))
    ap.add_argument("--all", action="store_true", help="处理所有天目录")
    ap.add_argument("--force", action="store_true", help="忽略已打标记录，重打")
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    dirs = []
    if args.all:
        dirs = [d for d in sorted(glob.glob(os.path.join(args.out, "20*"))) if os.path.isdir(d)]
    else:
        dirs = [args.out]

    tot_new = tot_all = 0
    for d in dirs:
        n, a = tag_day(d, args.record, args.threshold, args.force)
        print(f"[spk] {os.path.basename(d)}  新增 {n}/{a} 条")
        tot_new += n
        tot_all += a
    print(f"[spk] 合计 新增 {tot_new}/{tot_all} 条")


if __name__ == "__main__":
    main()
