# -*- coding: utf-8 -*-
"""全天音频 → 时间线（本地，零成本，可断点续跑）

用法:
    python pipeline.py <音频目录或单文件> [--out DIR] [--model small] [--jobs 1]

产出:
    <out>/timeline.jsonl   每行一段：绝对时间 + 文本 + 来源文件
    <out>/timeline.md      人读版，按小时分组
    <out>/_state.json      断点状态（重跑自动跳过已完成文件）

设计要点:
    - 文件按自然序排序（seg_2 在 seg_10 之前），偏移量按时长累加，
      不依赖文件创建时间（写盘时间晚于录音开始，不可靠）
    - 单文件超过 CHUNK 分钟自动分块，块间留 OVERLAP 秒重叠防切断词
    - condition_on_previous_text=False：避免长音频的复读死循环
"""
import os, sys, json, re, time, argparse
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import av
import numpy as np

SR = 16000
CHUNK = 30 * 60      # 单块最长 30 分钟（内存与失败重试的折中）
OVERLAP = 5          # 分块重叠秒数
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".mkv", ".mov"}

HERE = os.path.dirname(os.path.abspath(__file__))
_HOT = json.load(open(os.path.join(HERE, "hotwords.json"), encoding="utf-8"))
PROMPT = _HOT["initial_prompt"]
REPL = _HOT["replacements"]
_CC = None


def postproc(t):
    """繁转简 + 热词替换。whisper 中文常输出繁体，必须过一遍。"""
    global _CC
    if _CC is None:
        from opencc import OpenCC
        _CC = OpenCC("t2s")
    t = _CC.convert(t)
    for a, b in REPL:
        t = t.replace(a, b)
    return t


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def probe_duration(path):
    with av.open(path) as c:
        if c.duration:
            return float(c.duration) / 1e6
        # 容器没写总时长：解一遍估
        st = c.streams.audio[0]
        n = sum(f.samples for f in c.decode(st))
        return n / float(st.rate)


def load_audio(path, sr=SR):
    with av.open(path) as c:
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="fltp", layout="mono", rate=sr)
        chunks = []
        for fr in c.decode(st):
            for rf in rs.resample(fr):
                chunks.append(rf.to_ndarray())
        for rf in rs.resample(None):
            chunks.append(rf.to_ndarray())
    if not chunks:
        raise RuntimeError(f"没有音频流: {path}")
    return np.concatenate(chunks, axis=1).flatten().astype(np.float32)


def collect_files(target):
    if os.path.isfile(target):
        return [(os.path.abspath(target), 0.0, probe_duration(target))]
    out = []
    for root, _, names in os.walk(target):
        for n in names:
            if os.path.splitext(n)[1].lower() in AUDIO_EXT:
                out.append(os.path.join(root, n))
    out.sort(key=lambda p: natural_key(os.path.relpath(p, target)))
    seq, off = [], 0.0
    for p in out:
        d = probe_duration(p)
        seq.append((os.path.abspath(p), off, d))
        off += d
    return seq


def fmt(sec):
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def run(model, files, outdir, state_path):
    os.makedirs(outdir, exist_ok=True)
    state = {}
    if os.path.exists(state_path):
        state = json.load(open(state_path, encoding="utf-8"))

    jl = open(os.path.join(outdir, "timeline.jsonl"), "a", encoding="utf-8")
    total_audio = sum(d for _, _, d in files)
    done_audio = 0.0
    t_start = time.time()
    n_seg = 0

    for path, offset, dur in files:
        key = os.path.basename(path)
        if state.get(key, {}).get("done"):
            done_audio += dur
            n_seg += state[key].get("n", 0)
            print(f"[skip] {key}（已完成，{state[key].get('n',0)} 段）", flush=True)
            continue

        print(f"\n[file] {key}  偏移 {fmt(offset)}  时长 {dur/60:.1f} 分钟", flush=True)
        try:
            if dur <= CHUNK:
                blocks = [(0.0, dur)]
            else:
                blocks = []
                t = 0.0
                while t < dur:
                    e = min(t + CHUNK, dur)
                    blocks.append((t, e))
                    if e >= dur:
                        break
                    t = e - OVERLAP

            cnt = 0
            written_until = -1.0
            for bs, be in blocks:
                audio = load_audio(path)
                clip = audio[int(bs * SR):int(be * SR)]
                segments, info = model.transcribe(
                    clip, language="zh", beam_size=1, vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
                    condition_on_previous_text=False, word_timestamps=False,
                    initial_prompt=PROMPT or None,
                )
                for s in segments:
                    a = offset + bs + s.start
                    b = offset + bs + s.end
                    if a <= written_until:      # 重叠区去重
                        continue
                    txt = postproc(s.text.strip())
                    if not txt:
                        continue
                    rec = {"start": round(a, 2), "end": round(b, 2),
                           "t": fmt(a), "file": key, "text": txt}
                    jl.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    jl.flush()
                    written_until = b
                    cnt += 1
                    n_seg += 1
            state[key] = {"done": True, "n": cnt}
            json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False)
            done_audio += dur
            el = time.time() - t_start
            speed = done_audio / el if el else 0
            eta = (total_audio - done_audio) / speed / 60 if speed else 0
            print(f"[done] {key}: {cnt} 段 | 累计 {done_audio/60:.0f}/{total_audio/60:.0f} 分钟 "
                  f"| 速度 {speed:.2f}x 实时 | 剩余约 {eta:.0f} 分钟", flush=True)
        except Exception as e:
            print(f"[error] {key}: {e!r}", flush=True)
            state[key] = {"done": False, "error": str(e)}
            json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False)

    jl.close()
    render_md(outdir)
    print(f"\n[total] {n_seg} 段，用时 {(time.time()-t_start)/60:.1f} 分钟")


def render_md(outdir):
    src = os.path.join(outdir, "timeline.jsonl")
    if not os.path.exists(src):
        return
    recs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    recs.sort(key=lambda r: r["start"])
    lines = ["# 时间线", "", f"> 共 {len(recs)} 段，"
             f"{fmt(recs[0]['start'])} – {fmt(recs[-1]['end'])}" if recs else "> 空"]
    cur = None
    for r in recs:
        h = r["t"][:2]
        if h != cur:
            cur = h
            lines += ["", f"## {h}:00 – {h}:59", ""]
        lines.append(f"- `{r['t']}` {r['text']}")
    open(os.path.join(outdir, "timeline.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"[md] {os.path.join(outdir, 'timeline.md')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="small")
    args = ap.parse_args()

    outdir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.target)), "_timeline")
    files = collect_files(args.target)
    total = sum(d for _, _, d in files)
    print(f"[scan] {len(files)} 个文件，总时长 {total/3600:.2f} 小时")

    from faster_whisper import WhisperModel
    t = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=16)
    print(f"[load] {args.model} {time.time()-t:.1f}s")

    run(model, files, outdir, os.path.join(outdir, "_state.json"))


if __name__ == "__main__":
    main()
