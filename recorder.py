# -*- coding: utf-8 -*-
"""纯录制：只做一件事——把麦克风写成分片文件。内存占用 < 50MB。

设计原则:
    1. 只依赖 sounddevice + numpy，不加载模型、不做转写、不碰网络
    2. 每 --seconds 秒落一个 16k 单声道 wav，最坏情况只丢一段
    3. 时间轴由「启动时刻 + 累计样本数」推算，不依赖文件写盘时间
    4. Ctrl+C 会把剩余缓冲收尾，不留半截文件

用法:
    python recorder.py --out record --device "麦克风 (Realtek(R) Audio)"
    python recorder.py --list
"""
from data_location import data_root as default_data_root
from material_exchange import MaterialExchange
import os, sys, time, wave, argparse, datetime, threading, json
import numpy as np
import sounddevice as sd

SR = 48000            # USB 接收器只支持 48k（WASAPI 实测 16k 打不开）
BLOCK = SR // 10      # 0.1 秒


def segment_seconds(normal, outdir):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(outdir)), 'cloud-asr-trial.json'), encoding='utf-8') as file:
            state = json.load(file)
        if state.get('active') and state.get('deadline', 0) > time.time():
            return min(normal, 15)
    except (OSError, ValueError, TypeError):
        pass
    return normal


def acquire_single_instance(outdir):
    """单实例硬保证：多个 recorder 同时跑会生成同名文件互相覆盖、录音丢失。"""
    import singlelock
    return singlelock.acquire(os.path.join(outdir, ".recorder.lock"))


def write_wav(path, audio, sr=SR):
    """写完立刻落盘并改名为最终名，避免半截文件被下游读到。"""
    tmp = path + ".tmp"
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def pick_device():
    """优先 USB 接收器（UAC，48k 双声道），退回 DJI 蓝牙（HFP，16k 单声道）。
    UAC 只支持 48k；HFP 只支持 16k —— 采样率必须跟设备走，写错会直接打不开。"""
    ds = sd.query_devices()
    for pat, sr, ch in (("Wireless Mic", 48000, 2), ("DJI", 16000, 1), ("Realtek", 48000, 1)):
        for i, d in enumerate(ds):
            if d["max_input_channels"] < 1 or pat not in d["name"]:
                continue
            if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                return i, sr, ch
    try:
        index = sd.default.device[0]
        if index is not None and int(index) >= 0:
            device = sd.query_devices(int(index), 'input')
            if device['max_input_channels'] > 0:
                return int(index), int(device['default_samplerate']), 1
    except (ValueError, TypeError, sd.PortAudioError):
        pass
    raise RuntimeError('没有可用的默认录音设备；请连接麦克风，或用 --list 查看设备后用 --device 指定。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(default_data_root()))
    ap.add_argument("--out", default=None)
    ap.add_argument("--device", default="auto", help="编号 / 名字片段 / auto")
    ap.add_argument("--seconds", type=float, default=60.0, help="每段多少秒")
    ap.add_argument("--sr", type=int, default=None, help="采样率，默认跟设备走")
    ap.add_argument("--ch", type=int, default=None, help="输入声道数，默认跟设备走")
    ap.add_argument("--list", action="store_true")
    ap.add_argument('--stop-file', default=None, help='停止信号文件，供前台启动器使用')
    ap.add_argument('--ready-file', default=None, help='收到音频后创建的就绪信号')
    args = ap.parse_args()
    args.out = args.out or str(MaterialExchange(args.root).recording_directory())

    if args.list:
        print(sd.query_devices())
        return

    # 设备解析：auto / 数字编号 / 名字片段
    dev = args.device
    sr, ch = args.sr, args.ch
    if dev in (None, "", "auto"):
        dev, dev_sr, dev_ch = pick_device()
        sr = sr or dev_sr
        ch = ch or dev_ch
        print(f"[rec] 自动选择设备 [{dev}] {sd.query_devices(dev)['name'] if dev is not None else '未找到'}"
              f"  {sr}Hz/{ch}ch", flush=True)
    elif isinstance(dev, str) and dev.strip().isdigit():
        dev = int(dev.strip())
    sr = sr or SR
    ch = ch or 1

    os.makedirs(args.out, exist_ok=True)
    single = acquire_single_instance(args.out)
    if single is None:
        print("[rec] 已有 recorder 在运行（单实例锁被占用），本次退出。", flush=True)
        return
    buf = []
    lock = threading.Lock()
    stop = threading.Event()
    has_input = threading.Event()

    def cb(indata, frames, t, status):
        with lock:
            buf.append(indata[:, 0].copy())
        if frames:
            has_input.set()

    t0 = datetime.datetime.now()
    written = 0          # 已写样本数
    n_seg = 0

    try:
      while not stop.is_set():
       try:
        if args.stop_file and os.path.exists(args.stop_file):
            stop.set(); break
        # Recreate PortAudio after device loss or resume; its device list is cached.
        if args.device == "auto":
            sd._terminate()
            sd._initialize()
            dev, detected_sr, detected_ch = pick_device()
            sr, ch = args.sr or detected_sr, args.ch or detected_ch
        with sd.InputStream(samplerate=sr, blocksize=max(1, sr // 10), channels=ch,
                            dtype="float32", device=dev, callback=cb):
            print(f"[rec] 开始 → {args.out}  {sr}Hz/{ch}ch  每 {args.seconds:.0f}s 一段  Ctrl+C 结束", flush=True)
            if args.ready_file:
                deadline = time.monotonic() + 5
                while not has_input.is_set() and time.monotonic() < deadline:
                    if args.stop_file and os.path.exists(args.stop_file):
                        stop.set(); break
                    time.sleep(.05)
                if stop.is_set(): break
                if not has_input.is_set(): raise RuntimeError('Audio callback did not start')
                with open(args.ready_file, 'w', encoding='ascii') as ready:
                    ready.write(str(os.getpid()))
                has_input.clear()
                last_input_at = time.monotonic()
            while not stop.is_set():
                if not args.stop_file and not args.ready_file:
                    time.sleep(segment_seconds(args.seconds,args.out))
                else:
                    deadline=time.monotonic()+segment_seconds(args.seconds,args.out)
                    while time.monotonic()<deadline:
                        if args.stop_file and os.path.exists(args.stop_file):
                            stop.set(); break
                        if args.ready_file:
                            if has_input.is_set():
                                has_input.clear()
                                last_input_at = time.monotonic()
                                if not os.path.exists(args.ready_file):
                                    with open(args.ready_file, 'w', encoding='ascii') as ready:
                                        ready.write(str(os.getpid()))
                            elif time.monotonic() - last_input_at >= 5:
                                try: os.unlink(args.ready_file)
                                except FileNotFoundError: pass
                        time.sleep(min(0.2, max(0, deadline-time.monotonic())))
                with lock:
                    if not buf:
                        if stop.is_set(): break
                        raise RuntimeError("Audio callback stopped; reopening microphone")
                    audio = np.concatenate(buf)
                    buf.clear()
                start_ts = datetime.datetime.now() - datetime.timedelta(seconds=len(audio) / sr)
                written += len(audio)
                n_seg += 1
                name = start_ts.strftime("%Y%m%d_%H%M%S") + f"_{n_seg:04d}.wav"
                path = os.path.join(args.out, name)
                write_wav(path, audio, sr)
                print(f"[rec] {name}  {len(audio)/sr:.1f}s", flush=True)
       except Exception as e:
        if args.ready_file:
            try: os.unlink(args.ready_file)
            except FileNotFoundError: pass
        has_input.clear()
        print(f"[rec][retry] {type(e).__name__}: {e}", flush=True)
        for _ in range(25):
            if args.stop_file and os.path.exists(args.stop_file):
                stop.set(); break
            time.sleep(.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if args.ready_file:
            try: os.unlink(args.ready_file)
            except FileNotFoundError: pass
        with lock:
            if buf:
                audio = np.concatenate(buf)
                start_ts = datetime.datetime.now() - datetime.timedelta(seconds=len(audio) / sr)
                written += len(audio)
                n_seg += 1
                name = start_ts.strftime("%Y%m%d_%H%M%S") + f"_{n_seg:04d}.wav"
                path = os.path.join(args.out, name)
                write_wav(path, audio, sr)
                print(f"[rec] {name}  {len(audio)/sr:.1f}s（收尾）", flush=True)
        print(f"[rec] 结束，共 {n_seg} 段，{written/sr/60:.1f} 分钟", flush=True)
        if hasattr(single,'close'):single.close()


if __name__ == "__main__":
    main()
