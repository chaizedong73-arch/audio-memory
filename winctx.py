# -*- coding: utf-8 -*-
"""最小窗口采集器：只记「前台窗口变了」，不做识别、不录屏、不注入。

用途：给录音时间线补上下文（"你说这句话的时候在哪个窗口"）。
开销：每秒一次 GetForegroundWindow，只在变化时写一行，一天约几百 KB。

输出：winlog/YYYYMMDD.jsonl，每行
    {"ts": 1760943600.0, "t": "15:26:40", "proc": "keil.exe", "title": "..."}

用法:
    python winctx.py --out winlog
"""
import os, sys, json, time, ctypes, argparse, datetime
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_foreground_info():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value.strip()
    if not title:
        return None

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    proc = ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if h:
        try:
            size = wintypes.DWORD(1024)
            pbuf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                proc = os.path.basename(pbuf.value)
        finally:
            kernel32.CloseHandle(h)
    return {"proc": proc or f"pid{pid.value}", "title": title}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "winlog"))
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    import singlelock
    _lk = singlelock.acquire(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          ".locks", "winctx.lock"))
    if _lk is None:
        print("[win] 已有 winctx 在运行，退出。", flush=True)
        return

    os.makedirs(args.out, exist_ok=True)
    path = None
    cur_day = None
    last = None
    n = 0
    print(f"[win] 监听前台窗口 → {args.out}  间隔 {args.interval}s", flush=True)

    try:
        while True:
            # 跨午夜要换文件。旧版只在启动时算一次日期，整夜都写进启动那天的文件，
            # 凌晨的记录会被算成前一天 —— 记忆抽取按日期匹配窗口时必然错配。
            today = datetime.date.today().strftime("%Y%m%d")
            if today != cur_day:
                cur_day = today
                path = os.path.join(args.out, today + ".jsonl")
                print(f"[win] 切到 {path}", flush=True)

            info = get_foreground_info()
            if info:
                key = (info["proc"], info["title"])
                if key != last:
                    last = key
                    now = time.time()
                    rec = {
                        "ts": round(now, 1),
                        "t": datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S"),
                        "date": datetime.date.today().isoformat(),
                        "proc": info["proc"],
                        "title": info["title"][:200],
                    }
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
                    print(f"[win] {rec['t']} {rec['proc']} | {rec['title'][:60]}", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"[win] 结束，共 {n} 条", flush=True)


if __name__ == "__main__":
    main()
