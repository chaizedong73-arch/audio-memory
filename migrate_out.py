# -*- coding: utf-8 -*-
"""一次性迁移脚本：修正旧版输出布局的三个问题。

旧版问题
--------
    1. 状态文件 _transcribed.json 放在 out/YYYYMMDD/ 里 → 每天新建目录 → 状态为空
       → 昨天的录音被整个重转一遍（实测 21 日目录里 435 行来自 20 日）
    2. 时间轴基准是「全局第一个录音文件」→ start 能到 6 万秒，跨天后 cursor 语义错乱
    3. timeline 按「运行当天」落盘 → 目录里混着前一天的记录

新布局
------
    out/_transcribed.json          全局状态（跨天不重转）
    out/YYYYMMDD/timeline.jsonl    按录音文件自身日期落盘
    start = 当天 00:00 起的秒数，另附 ts（epoch）与 date

用法:
    python migrate_out.py --dry     # 只报告
    python migrate_out.py            # 执行（会先备份）
"""
import os, sys, json, glob, shutil, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
RECORD = os.path.join(HERE, "record")


def base_ts_from_record():
    """旧版基准 = record 目录里最早的那个 wav 的起始时间。"""
    files = sorted(glob.glob(os.path.join(RECORD, "*.wav")))
    for f in files:
        n = os.path.basename(f)
        try:
            return datetime.datetime.strptime(n[:15], "%Y%m%d_%H%M%S").timestamp()
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    daydirs = sorted([d for d in glob.glob(os.path.join(OUT, "20*")) if os.path.isdir(d)])
    if not daydirs:
        print("没有找到任何 out/YYYYMMDD 目录")
        return

    base = base_ts_from_record()
    print(f"旧版时间轴基准（record 里最早的 wav）：{base}")
    if base is None:
        print("找不到基准 wav，无法迁移时间轴")
        return

    # 1) 收集所有 timeline 行
    all_rows = []
    for d in daydirs:
        tl = os.path.join(d, "timeline.jsonl")
        if not os.path.exists(tl):
            continue
        for line in open(tl, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                all_rows.append(json.loads(line))
            except Exception:
                pass
    print(f"读入 {len(all_rows)} 行（来自 {len(daydirs)} 个目录）")

    # 2) 去重：同一 file+start+text 只保留一条
    seen, rows = set(), []
    for r in all_rows:
        k = (r.get("file"), r.get("start"), r.get("text"))
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)
    print(f"去重后 {len(rows)} 行（去掉 {len(all_rows)-len(rows)} 行重复）")

    # 3) 转成新格式并按日期分组
    by_day = {}
    for r in rows:
        ts = base + float(r["start"])
        dt = datetime.datetime.fromtimestamp(ts)
        day = dt.strftime("%Y%m%d")
        d0 = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        r2 = dict(r)
        r2["start"] = round((dt - d0).total_seconds(), 2)
        r2["end"] = round(r2["start"] + (float(r.get("end", 0)) - float(r.get("start", 0))), 2)
        r2["ts"] = round(ts, 2)
        r2["t"] = dt.strftime("%H:%M:%S")
        r2["date"] = dt.strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(r2)

    for day in sorted(by_day):
        rs = sorted(by_day[day], key=lambda x: x["start"])
        d = os.path.join(OUT, day)
        os.makedirs(d, exist_ok=True)
        print(f"  {day}: {len(rs)} 行 → {d}")
        if args.dry:
            continue
        bak = os.path.join(d, "timeline.jsonl.bak")
        if os.path.exists(os.path.join(d, "timeline.jsonl")):
            if not os.path.exists(bak):
                shutil.copy2(os.path.join(d, "timeline.jsonl"), bak)
        with open(os.path.join(d, "timeline.jsonl"), "w", encoding="utf-8") as fo:
            for r in rs:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 4) 全局状态：合并各目录的 _transcribed.json
    merged = {}
    for d in daydirs:
        sp = os.path.join(d, "_transcribed.json")
        if os.path.exists(sp):
            try:
                merged.update(json.load(open(sp, encoding="utf-8")))
            except Exception:
                pass
    print(f"合并状态 {len(merged)} 条 → out/_transcribed.json")
    if not args.dry:
        json.dump(merged, open(os.path.join(OUT, "_transcribed.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        # 各目录里的旧状态改名，避免被误读
        for d in daydirs:
            sp = os.path.join(d, "_transcribed.json")
            if os.path.exists(sp):
                os.replace(sp, sp + ".bak")

    # 5) 游标清零（时间轴基准变了，旧游标值无意义）
    if not args.dry:
        for d in daydirs:
            cp = os.path.join(d, "_cursor.json")
            if os.path.exists(cp):
                os.replace(cp, cp + ".bak")
        print("旧游标已备份为 .bak（时间轴基准变更，游标需重算）")
    print("完成")


if __name__ == "__main__":
    main()
