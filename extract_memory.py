# -*- coding: utf-8 -*-
"""时间线 → 记忆条目（增量、带防幻觉校验）

用法:
    python extract_memory.py <目录或 timeline.jsonl> [--minutes 10] [--force] [--dry]

增量机制:
    读 <dir>/_cursor.json 的 until（已处理到录音的第几秒），
    只处理 start >= until 的记录；处理完把 until 推进到最后一个完整块的末尾。
    最后一块若不足 --minutes 的 80%，留到下次，避免把半句话切成事件。

输出:
    memory.jsonl   累计追加，每行一条记忆
    memory.md      全部记忆的渲染版

防幻觉:
    quote 必须能在原文里找到（繁转简 + 去标点后比对），
    拼接多句时按句拆开逐句校验。对不上的标 quote_ok=false。
"""
import os, sys, json, re, subprocess, tempfile, argparse, datetime

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'ark_config.json')

PROMPT = """你在整理一个人一段时间的声音记录。可能是对话、自言自语、上课、开会、走路时的碎碎念。
没有画面、没有窗口信息，**只有声音**。这是正常的，不要因为没有画面就不提取。

目标：让三天后的他，只看你写的东西，就能想起这段时间发生了什么、答应了什么、想到了什么。

按类型提取，每条必须有原文引用：

1. **todo** 待办 / 承诺：答应别人或自己要做的事。
   信号："我明天要…"、"你记得…"、"下周…"、"回头把…"、"得去…"
2. **idea** 想法 / 决定 / 判断：冒出来的点子、改了主意、对某事的看法。
   信号："我觉得…"、"其实应该…"、"不如…"、"决定…"、"好像可以…"
3. **fact** 事实 / 新信息：听到或学到的、之前不知道的事。
   信号："原来…"、"他说…"、"查了一下…"、"是因为…"
4. **event** 事件：发生了一件具体的事（做了什么、去了哪、见了谁）。
5. **dialogue** 对话要点：跟别人的一段对话里，值得记的那一句。
6. **emotion** 情绪：明显的烦躁、兴奋、担心、疲惫。只在情绪很强烈时提。

不是每种都有。某个类型这段没有，就不要硬凑。
**宁可少提，不要编造。** 废话、寒暄、"嗯""那个"、明显乱码，一律不要。
如果整段确实没什么内容，返回 {"items": []}。

每条格式（新增 speaker_kind 人物验证，2026-10-21）：
{"type":"todo|idea|fact|event|dialogue|emotion",
 "text":"一句话说清（不超过 35 字）",
 "who":["涉及的人，没有就空数组"],
 "speaker_kind":"self|other|unclear",
 "quote":"逐字摘录原文（10-60 字），必须原样复制，只摘连续的一段"}

**人物验证（重要，直接决定可信度）**：
- `speaker_kind="self"`：**用户本人**说的 / 想的 / 答应的。todo、idea、emotion **只能**是 self——别人说的话不能算成用户的待办或想法。
- `speaker_kind="other"`：**别人**说的（对话里对方、旁人、电视里的声音）。别人的承诺/观点记为 dialogue/fact，不要记成用户的 todo/idea。
- `speaker_kind="unclear"`：分不清谁说的、单人自言自语但无法确认身份、环境噪音里的碎片。
**判断不出就填 unclear，不要猜。** 把别人的话错记成用户的，是这个系统最严重的错误。

只输出 JSON，不要解释，不要 markdown 代码块。
格式：{"items":[...]}
"""


# ---------- 文本归一化与校验 ----------
_CC = None


def norm(s):
    global _CC
    if _CC is None:
        from opencc import OpenCC
        _CC = OpenCC("t2s")
    s = _CC.convert(s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[，。！？、,.!?；;：:、“”‘’\"'（）()\[\]【】…—\-·]", "", s)
    return s.lower()


def quote_support(q, text_n):
    qn = norm(q)
    if not qn:
        return False, 0.0
    if qn in text_n:
        return True, 1.0
    parts = [norm(p) for p in re.split(r"[。！？!?；;…]", q) if norm(p)]
    if not parts:
        return False, 0.0
    hit = sum(1 for p in parts if p in text_n)
    return hit == len(parts), hit / len(parts)


# ---------- LLM ----------
def call_llm(system, user, timeout=300):
    cfg = json.load(open(CFG, encoding="utf-8"))
    body = {
        "model": cfg["asr_model"],
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(body, tf, ensure_ascii=False)
        bf = tf.name
    p = subprocess.run(
        ["curl", "-sS", "--fail", "--noproxy", "*", "-X", "POST",
         f"{cfg['ark_base_url']}/chat/completions",
         "-H", f"Authorization: Bearer {cfg['ark_api_key']}",
         "-H", "Content-Type: application/json",
         "-d", f"@{bf}"],
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    os.unlink(bf)
    if p.returncode != 0:
        raise RuntimeError(f"curl rc={p.returncode}: {p.stderr[:300]}")
    data = json.loads(p.stdout)
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False)[:400])
    msg = data["choices"][0]["message"]["content"]
    if isinstance(msg, list):
        msg = "".join(c.get("text", "") for c in msg if isinstance(c, dict))
    return msg.strip()


def parse_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    t = t.strip()
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return json.loads(t)


# ---------- 分块 ----------
def hms_to_sec(hms):
    try:
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except Exception:
        return None


def load_winlog(pattern_or_dir):
    """读窗口日志（winctx.py 的产物），返回按时间排序的记录。"""
    import glob
    files = []
    if os.path.isdir(pattern_or_dir):
        files = sorted(glob.glob(os.path.join(pattern_or_dir, "*.jsonl")))
    elif os.path.exists(pattern_or_dir):
        files = [pattern_or_dir]
    recs = []
    for f in files:
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    recs.sort(key=lambda r: r.get("ts", 0))
    return recs


def windows_in_range(winrecs, start_ts, end_ts, limit=12):
    """取 [start_ts, end_ts]（绝对 epoch 秒）内出现过的窗口，按首次出现顺序去重。

    2026-10-21 修正：旧版用 HH:MM:SS 的"当天秒数"比较，跨午夜必然错配
    （23:50 的录音和 00:10 的窗口被算成同一时段）。改用 epoch 绝对时间。
    """
    seen, out = set(), []
    for r in winrecs:
        sec = r.get("ts")
        if sec is None or sec < start_ts or sec > end_ts:
            continue
        key = (r.get("proc", ""), (r.get("title") or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{r.get('proc','?')} | {r.get('title','')[:60]}")
        if len(out) >= limit:
            break
    return out


def chunk(recs, minutes):
    """按时间切块，返回 [(块内记录, 块起点, 块终点)]。"""
    if not recs:
        return []
    out, cur, base = [], [], recs[0]["start"]
    for r in recs:
        if cur and r["start"] - base > minutes * 60:
            out.append((cur, cur[0]["start"], cur[-1]["end"]))
            cur, base = [], r["start"]
        cur.append(r)
    if cur:
        out.append((cur, cur[0]["start"], cur[-1]["end"]))
    return out


def load_speaker_map(outdir):
    """读同目录的 speaker.jsonl（说话人标签侧车文件）。

    为什么不直接往 timeline.jsonl 里写 speaker 字段：
    timeline.jsonl 是 transcriber 持续追加的文件，抽取器改写它会和转写进程
    抢文件（丢行 / 半行）。侧车文件是独立文件，只追加不冲突。
    """
    p = os.path.join(outdir, "speaker.jsonl")
    m = {}
    if not os.path.exists(p):
        return m
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            m[(r.get("file"), round(float(r.get("start", 0)), 2))] = r.get("speaker")
        except Exception:
            pass
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--force", action="store_true", help="连最后不完整的一块也处理")
    ap.add_argument("--winlog", default=None, help="窗口日志目录或文件，用于给记忆补上下文")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    path = args.target
    if os.path.isdir(path):
        path = os.path.join(path, "timeline.jsonl")
    if not os.path.exists(path):
        print(f"[err] 找不到 {path}")
        return
    outdir = os.path.dirname(os.path.abspath(path))
    cursor_path = os.path.join(outdir, "_cursor.json")
    mem_path = os.path.join(outdir, "memory.jsonl")

    recs_all = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    recs_all.sort(key=lambda r: r["start"])

    # 合并说话人标签（侧车文件）
    spk_map = load_speaker_map(outdir)
    if spk_map:
        hit = 0
        for r in recs_all:
            s = spk_map.get((r.get("file"), round(float(r.get("start", 0)), 2)))
            if s:
                r["speaker"] = s
                hit += 1
        print(f"[spk] 合并 {hit}/{len(recs_all)} 条说话人标签")

    cursor = {"until": 0.0}
    if os.path.exists(cursor_path):
        cursor = json.load(open(cursor_path, encoding="utf-8-sig"))

    # 游标语义：until = 已处理到的「时间点」。用 end > until 而不是 start >= until，
    # 这样跨游标的那一条（start < until < end）不会被漏掉，也不会重复处理已完整覆盖的段。
    new = [r for r in recs_all if r.get("end", r["start"]) > cursor["until"]]
    if not new:
        print(f"[skip] 没有新内容（已处理到 {cursor['until']:.0f}s，文件共 {len(recs_all)} 段）")
        return

    blocks = chunk(new, args.minutes)
    # 最后一块不完整 → 留着下次
    if not args.force and len(blocks) > 1:
        last_dur = blocks[-1][2] - blocks[-1][1]
        if last_dur < args.minutes * 60 * 0.8:
            blocks = blocks[:-1]
    if not blocks:
        print(f"[wait] 新增内容还不足一个完整块（{len(new)} 段），等下次")
        return

    print(f"[in] 新 {len(new)} 段 → {len(blocks)} 块（每块 {args.minutes} 分钟）")
    if args.dry:
        for i, (blk, s, e) in enumerate(blocks, 1):
            print(f"  块{i} {s:.0f}-{e:.0f}s  {len(blk)} 段")
        return

    stats = {"total": 0, "ok": 0, "partial": 0, "trusted": 0, "dups": 0}
    fout = open(mem_path, "a", encoding="utf-8")
    last_end = cursor["until"]
    # 跨轮去重：读历史 memory.jsonl 的 key，避免同一记忆重复追加
    seen_keys = set()
    if os.path.exists(mem_path):
        for _ln in open(mem_path, encoding="utf-8"):
            _ln = _ln.strip()
            if not _ln:
                continue
            try:
                _r = json.loads(_ln)
                seen_keys.add((_r.get("type"), _r.get("text", ""), (_r.get("quote") or "")[:40]))
            except Exception:
                pass

    winrecs = load_winlog(args.winlog) if args.winlog else []
    if args.winlog:
        print(f"[winlog] {len(winrecs)} 条窗口记录" if winrecs else f"[winlog] {args.winlog} 没读到记录")

    for i, (blk, bs, be) in enumerate(blocks, 1):
        # 日期以音频文件名（20261020_...）为准，不能取 today()——跨午夜会把前一天标成今天
        _fd = (blk[0].get("file") or "")[:8]
        blk_date = (f"{_fd[:4]}-{_fd[4:6]}-{_fd[6:8]}"
                    if (len(_fd) == 8 and _fd.isdigit())
                    else datetime.date.today().isoformat())
        span = f"{blk[0]['t']}-{blk[-1]['t']}"
        text = "\n".join(f"[{r['t']}] {r['text']}" for r in blk)
        plain = "\n".join(r["text"] for r in blk)
        tn = norm(plain)

        # 窗口上下文：把这段时间前台开过什么告诉模型
        ctx = ""
        if winrecs:
            ts0 = blk[0].get("ts")
            ts1 = blk[-1].get("ts")
            if ts0 is not None and ts1 is not None:
                ws = windows_in_range(winrecs, ts0, ts1)
                if ws:
                    ctx = ("当时前台开过的窗口（按出现顺序，可用来判断在做什么）：\n"
                           + "\n".join(f"- {w}" for w in ws) + "\n\n")
        # 说话人信息（若时间线已打过标）
        spk = sorted({r.get("speaker") for r in blk if r.get("speaker")})
        spk_ctx = ""
        if spk:
            spk_ctx = ("这段涉及的说话人标签（可能不准，仅供参考）：" + "、".join(spk) + "\n\n")
        try:
            obj = parse_json(call_llm(PROMPT, f"时间段 {span}\n\n{ctx}{spk_ctx}语音转写：\n{text}"))
        except Exception as e:
            print(f"[warn] 块{i} {span} 失败: {e!r}")
            # 关键：失败块必须中断，不能 continue。
            # 旧版 continue 后，后面的块成功会把 last_end 推过失败块 → 失败块被永久跳过，
            # 那段时间的记忆就永久丢了。这里改成 break，游标只推进到最后一块成功的。
            print(f"[warn] 中止本轮后续块（避免游标越过失败块导致丢内容）")
            break
        n = 0
        blk_spk = [r.get("speaker") for r in blk if r.get("speaker")]
        dom_spk = max(set(blk_spk), key=blk_spk.count) if blk_spk else None
        for b in obj.get("items", []):
            typ = (b.get("type") or "event").strip().lower()
            if typ not in ("todo", "idea", "fact", "event", "dialogue", "emotion"):
                typ = "event"
            b["type"] = typ
            b["range"] = span          # 时间以块的真实起止为准，不用模型编的
            b["date"] = blk_date
            b["speaker"] = dom_spk     # 块内主导说话人（时间线标签，可能是"新人X"）
            # --- 人物验证（2026-10-21）：模型判 self/other/unclear，但实测不可靠 ---
            # 实测：他人对用户说的话被模型错判为 self（"你明天记得把报告发给我"→self）。
            # 结论：单靠 prompt 判身份不可信（正是行业"分不清谁说的"死穴）。
            # 故 speaker_kind 仅作参考，一律不据此标 trusted；身份靠人工问卷确认。
            mdl_kind = (b.get("speaker_kind") or "").strip().lower()
            if mdl_kind not in ("self", "other", "unclear"):
                mdl_kind = "unclear"
            b["speaker_kind"] = mdl_kind          # 模型参考
            b["speaker_verified"] = False         # 一律待人工确认，不轻信模型
            if not b.get("who") and dom_spk and not str(dom_spk).startswith("新人"):
                b["who"] = [dom_spk]   # 有注册名时补上，模型没填也能知道谁说的
            q = (b.get("quote") or "").strip()
            ok, cov = quote_support(q, tn)
            b["quote_ok"] = ok
            b["quote_coverage"] = round(cov, 2)
            # --- 可信分层（2026-10-21）：身份永远待人工确认，引文可验证即 worth_review ---
            # trusted 仅表示"引文能在原文找到"（防幻觉层面可信），不代表身份对。
            # 身份（谁说的）一律 speaker_verified=False，交网页问卷由用户确认。
            trusted = bool(ok)   # 仅引文维度
            b["trusted"] = trusted
            b["needs_review"] = True   # 所有条目都需人工过一遍（尤其身份）
            b["review_reason"] = (
                "" if trusted else "引文未通过"
            )
            # --- 跨轮去重（2026-10-21 修复）：写入前查重，避免同一记忆重复追加 ---
            dkey = (typ, b.get("text", ""), q[:40])
            if dkey in seen_keys:
                stats["dups"] = stats.get("dups", 0) + 1
                continue
            seen_keys.add(dkey)
            stats["total"] += 1
            stats[f"t_{typ}"] = stats.get(f"t_{typ}", 0) + 1
            if ok:
                stats["ok"] += 1
            elif cov >= 0.8:
                stats["partial"] += 1
            if trusted:
                stats["trusted"] = stats.get("trusted", 0) + 1
            fout.write(json.dumps(b, ensure_ascii=False) + "\n")
            n += 1
        fout.flush()
        last_end = be
        print(f"[{i}/{len(blocks)}] {span} → {n} 条")

    fout.close()
    cursor["until"] = last_end
    cursor["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(cursor, open(cursor_path, "w", encoding="utf-8"), ensure_ascii=False)

    render_md(mem_path, outdir)
    dist = {k[2:]: v for k, v in stats.items() if k.startswith("t_")}
    print(f"\n[sum] 本次 {stats['total']} 条，完全可验证 {stats['ok']}，部分 {stats['partial']}，去重跳过 {stats.get('dups',0)}")
    print(f"[可信] trusted={stats.get('trusted',0)} / {stats['total']}  待人工复核={stats['total']-stats.get('trusted',0)}（他人/不明/引文未过）")
    if dist:
        print(f"[类型] " + "  ".join(f"{k}:{v}" for k, v in dist.items()))
    print(f"[cursor] 已推进到第 {last_end:.0f} 秒")


def render_md(mem_path, outdir):
    if not os.path.exists(mem_path):
        return
    rows = [json.loads(l) for l in open(mem_path, encoding="utf-8") if l.strip()]
    ok = sum(1 for r in rows if r.get("quote_ok"))

    LABEL = {"todo": "待办", "idea": "想法", "fact": "事实",
             "event": "事件", "dialogue": "对话", "emotion": "情绪"}
    ORDER = ["todo", "idea", "fact", "dialogue", "event", "emotion"]

    md = ["# 记忆条目", "",
          f"> 累计 {len(rows)} 条，原文可验证 {ok} 条（{ok/max(len(rows),1)*100:.0f}%）", ""]

    # 顶部速览：待办 + 想法，这两类最容易被用到
    quick_todo = [r for r in rows if r.get("type") == "todo"]
    quick_idea = [r for r in rows if r.get("type") == "idea"]
    if quick_todo:
        md += ["## 待办速览", ""]
        for r in quick_todo:
            md.append(f"- [ ] {r.get('text','')}  ·{r.get('range','')}")
        md.append("")
    if quick_idea:
        md += ["## 想法速览", ""]
        for r in quick_idea:
            md.append(f"- {r.get('text','')}  ·{r.get('range','')}")
        md.append("")

    for typ in ORDER:
        group = [r for r in rows if r.get("type") == typ]
        if not group:
            continue
        md += [f"---", "", f"## {LABEL[typ]}（{len(group)}）", ""]
        for r in group:
            flag = "" if r.get("quote_ok") else f" ⚠️引用覆盖率 {r.get('quote_coverage',0)}"
            who = f"（{'、'.join(r['who'])}）" if r.get("who") else ""
            md.append(f"- **{r.get('date','')} {r.get('range','')}** {r.get('text','')}{who}{flag}")
            if r.get("quote"):
                md.append(f"  > {r['quote']}")
        md.append("")

    open(os.path.join(outdir, "memory.md"), "w", encoding="utf-8").write("\n".join(md))
    print(f"[md] {os.path.join(outdir, 'memory.md')}")


if __name__ == "__main__":
    main()
