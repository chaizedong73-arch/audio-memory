"""One-shot, CPU-only Qwen3-ASR 0.6B acceptance probe. Does not touch live pipeline files."""
import argparse
import ctypes
import json
import time
from pathlib import Path



MODEL_ID = "Qwen/Qwen3-ASR-0.6B-hf"


def available_memory_mb():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended_virtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return round(status.avail_phys / 1024 / 1024, 1)


def main():
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not args.audio.is_file():
        raise SystemExit(f"Audio not found: {args.audio}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    before = available_memory_mb()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    loaded = time.perf_counter()
    model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, dtype=torch.float32, device_map="cpu").eval()
    ready = time.perf_counter()
    inputs = processor.apply_transcription_request(audio=str(args.audio), language="Chinese").to("cpu", torch.float32)
    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=256, do_sample=False)
    done = time.perf_counter()
    generated = output_ids[:, inputs["input_ids"].shape[1]:]
    result = processor.decode(generated, return_format="parsed")[0]
    report = {
        "model": MODEL_ID,
        "backend": "CPU / float32 / Windows",
        "audio": str(args.audio),
        "audioBytes": args.audio.stat().st_size,
        "threads": args.threads,
        "memoryAvailableMB": {"before": before, "after": available_memory_mb()},
        "seconds": {"processor": round(loaded - started, 2), "modelLoad": round(ready - loaded, 2), "inference": round(done - ready, 2), "total": round(done - started, 2)},
        "result": result,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
