"""Resolve user data separately from application files."""
import os
from pathlib import Path

def data_root():
    configured = os.environ.get("AUDIO_MEMORY_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parent.parent / "数据"
