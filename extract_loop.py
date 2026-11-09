# -*- coding: utf-8 -*-
"""常驻抽取器：每 --every 秒对 out/ 下各天目录增量抽一次记忆。

2026-10-21 修正：
    - 旧版只处理 --out 指向的当天目录，而 transcriber 的输出按录音日期落盘，
      跨天后当天的目录里可能没有新内容、旧目录反而积压 → 现在遍历 out/*/YYYYMMDD。
    - 每轮只把「新增时间线」送进 LLM，已处理的靠 _cursor.json 跳过。
    - 窗口上下文（--winlog）现在真的传下去了 —— 旧版从未启用这个功能。
    - 子进程加 CREATE_NO_WINDOW，父进程用 pythonw 拉起时不再每 10 分钟弹窗。

用法:
    python extract_loop.py --out out --minutes 10 --every 600
"""
from data_location import data_root as default_data_root
import os, sys, time, subprocess, argparse, glob

HERE = os.path.dirname(os.path.abspath(__file__))


def day_dirs(outroot):
    ds = [d for d in sorted(glob.glob(os.path.join(outroot, "20*"))) if os.path.isdir(d)]
    return [d for d in ds if os.path.exists(os.path.join(d, "timeline.jsonl"))]


def run_speaker_tag(record_dir, outroot, threshold=None):
    """给所有天目录打说话人标签（独立子进程，失败不影响抽取）。"""
    script = os.path.join(HERE, "speaker_tag.py")
    cmd = [sys.executable, script, "--out", outroot, "--record", record_dir, "--all"]
    if threshold:
        cmd += ["--threshold", str(threshold)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (p.stdout or "").splitlines():
            if line.strip():
                print(f"  [spk] {line}", flush=True)
        if p.returncode != 0:
            print(f"  [spk][err] {(p.stderr or '')[:200]}", flush=True)
    except Exception as e:
        print(f"  [spk][fail] {e!r}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(str(default_data_root()), "out"))
    ap.add_argument("--record", default=os.path.join(str(default_data_root()), "record"))
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--every", type=float, default=600.0)
    ap.add_argument("--winlog", default=os.path.join(str(default_data_root()), "winlog"))
    ap.add_argument("--no-speaker", action="store_true", help="跳过说话人打标")
    ap.add_argument("--speaker-threshold", type=float, default=None)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    import singlelock
    _lk = singlelock.acquire(os.path.join(HERE, ".locks", "extract.lock"))
    if _lk is None:
        print("[extract] 已有 extract_loop 在运行，退出。", flush=True)
        return

    script = os.path.join(HERE, "extract_memory.py")
    py = sys.executable
    winlog = args.winlog if os.path.isdir(args.winlog) else None
    print(f"[extract] 每 {args.every:.0f}s 抽一次（块 {args.minutes} 分钟）→ {args.out}"
          + (f"  窗口上下文 {winlog}" if winlog else "  无窗口上下文"), flush=True)

    while True:
        ds = day_dirs(args.out)
        if not ds:
            print("  没有可抽取的时间线", flush=True)
        for d in ds:
            cmd = [py, script, d, "--minutes", str(args.minutes)]
            if winlog:
                cmd += ["--winlog", winlog]
            try:
                p = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=1800,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = (p.stdout or "").strip()
                tag = os.path.basename(d)
                if out:
                    for line in out.splitlines():
                        print(f"  [{tag}] {line}", flush=True)
                if p.returncode != 0:
                    print(f"  [{tag}][err] {(p.stderr or '')[:300]}", flush=True)
            except Exception as e:
                print(f"  [{tag}][fail] {e!r}", flush=True)

        # Optional speaker enrichment must not block the primary memory pipeline.
        if not args.no_speaker:
            run_speaker_tag(args.record, args.out, args.speaker_threshold)
        if args.once:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
