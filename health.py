# -*- coding: utf-8 -*-
"""健康看板：一屏看清录音 / 转写 / 抽取 / 说话人四层是否活着、落后多少。

为什么需要
----------
    这套系统是四个独立进程 + 磁盘当队列，任何一层卡住都不会"报错"，
    只会安静地不产出。早上出现过转写落后 4 小时、窗口上下文从未启用、
    记忆停更的情况，都没有告警 —— 因为没人知道该看哪。

用法:
    python health.py              # 概览
    python health.py --json       # 机器可读
"""
import os, sys, json, glob, time, argparse, datetime, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "record")
OUT = os.path.join(HERE, "out")
WINLOG = os.path.join(HERE, "winlog")


def file_age(p):
    if not os.path.exists(p):
        return None
    return time.time() - os.path.getmtime(p)


def fmt_age(sec):
    if sec is None:
        return "—"
    if sec < 60:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{sec/60:.0f}分"
    if sec < 86400:
        return f"{sec/3600:.1f}小时"
    return f"{sec/86400:.1f}天"


def proc_alive(pattern):
    """查命令行里含 pattern 的进程。

    注意：wmic 在新版 Windows 已移除（这里直接返回 None），必须走
    Get-CimInstance Win32_Process。用 PowerShell 而不是 ctypes，
    因为进程命令行信息只有 WMI 能拿到。
    """
    ps = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -like '*{pattern}*' -and $_.ProcessId -ne $PID }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode != 0:
            return None
        pids = [l.strip() for l in (p.stdout or "").splitlines()
                if l.strip().isdigit()]
        return pids
    except Exception:
        return None


def dir_size(p):
    tot = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = time.time()
    rec_files = sorted(glob.glob(os.path.join(RECORD, "*.wav")))
    latest_rec = rec_files[-1] if rec_files else None
    rec_age = file_age(latest_rec)

    # 转写状态
    state_path = os.path.join(OUT, "_transcribed.json")
    state = {}
    if os.path.exists(state_path):
        try:
            state = json.load(open(state_path, encoding="utf-8"))
        except Exception:
            pass
    transcribed = len(state)
    pending = [f for f in rec_files if os.path.splitext(os.path.basename(f))[0] not in state]

    # 每天的时间线/记忆
    days = []
    for d in sorted(glob.glob(os.path.join(OUT, "20*"))):
        if not os.path.isdir(d):
            continue
        tl = os.path.join(d, "timeline.jsonl")
        mem = os.path.join(d, "memory.md")
        cursor = os.path.join(d, "_cursor.json")
        n = 0
        if os.path.exists(tl):
            with open(tl, encoding="utf-8") as f:
                n = sum(1 for line in f if line.strip())
        cur = {}
        if os.path.exists(cursor):
            try:
                cur = json.load(open(cursor, encoding="utf-8"))
            except Exception:
                pass
        days.append({
            "day": os.path.basename(d),
            "timeline_lines": n,
            "memory_age": fmt_age(file_age(mem)),
            "cursor_until": cur.get("until"),
            "cursor_updated": cur.get("updated"),
            "speaker_lines": (sum(1 for line in open(os.path.join(d, "speaker.jsonl"), encoding="utf-8")
                                 if line.strip()) if os.path.exists(os.path.join(d, "speaker.jsonl")) else 0),
        })

    procs = {}
    for name, pat in (("recorder", "recorder.py"), ("transcriber", "transcriber.py"),
                      ("extract", "extract_loop.py"), ("winctx", "winctx.py")):
        r = proc_alive(pat)
        procs[name] = {"alive": (len(r) if r is not None else None), "pids": r}

    # 窗口日志
    wl = sorted(glob.glob(os.path.join(WINLOG, "*.jsonl")))
    wl_age = file_age(wl[-1]) if wl else None

    rec_size = dir_size(RECORD)
    model_size = dir_size(os.path.join(HERE, "models"))

    report = {
        "now": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "recorder": {"files": len(rec_files), "latest": os.path.basename(latest_rec) if latest_rec else None,
                     "age": fmt_age(rec_age), "age_sec": rec_age, "dir_size_mb": round(rec_size / 1048576)},
        "transcriber": {"transcribed": transcribed, "pending": len(pending),
                        "pending_head": [os.path.basename(p) for p in pending[:3]]},
        "extract": {"days": days},
        "winctx": {"files": len(wl), "age": fmt_age(wl_age), "age_sec": wl_age},
        "processes": procs,
        "models_size_mb": round(model_size / 1048576),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return

    print("=" * 58)
    print(f"  AI 录音记忆系统 · 健康看板   {report['now']}")
    print("=" * 58)

    r = report["recorder"]
    flag = "✅" if (r["age_sec"] is not None and r["age_sec"] < 300) else ("⚠️" if r["age_sec"] is not None else "❌")
    print(f"\n【录音】{flag} {r['files']} 段，最新 {r['latest']}（{r['age']}前）"
          f"  占用 {r['dir_size_mb']}MB")

    t = report["transcriber"]
    flag = "✅" if t["pending"] == 0 else ("⚠️" if t["pending"] < 60 else "❌")
    print(f"\n【转写】{flag} 已转 {t['transcribed']}，待转 {t['pending']}"
          + (f"  最早待转：{', '.join(t['pending_head'])}" if t["pending_head"] else ""))

    print("\n【抽取 · 按天】")
    for d in days:
        print(f"  {d['day']}  时间线 {d['timeline_lines']} 句  说话人 {d['speaker_lines']} 句"
              f"  记忆更新于 {d['memory_age']}前  游标 {d['cursor_until']}")
    if not days:
        print("  （无输出目录）")

    w = report["winctx"]
    flag = "✅" if (w["age_sec"] is not None and w["age_sec"] < 600) else ("⚠️" if w["age_sec"] is not None else "❌")
    print(f"\n【窗口上下文】{flag} {w['files']} 个日志文件，最新 {w['age']}前")

    print("\n【进程】")
    for name, v in procs.items():
        st = "✅ 运行中" if v["alive"] else ("❌ 未运行" if v["alive"] == 0 else "? 未知")
        print(f"  {name:11s} {st}" + (f"  PID {', '.join(v['pids'])}" if v["pids"] else ""))

    print(f"\n【磁盘】record {r['dir_size_mb']}MB   models {report['models_size_mb']}MB")
    print("=" * 58)


if __name__ == "__main__":
    main()
