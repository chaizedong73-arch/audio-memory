"""Run a local module with its output kept in a local log file."""
import argparse
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('script', type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    target = args.script.resolve(strict=True)
    if target.parent != root or target.name not in {'run_core.py', 'ai_material_gateway.py', 'visual_worker.py'}:
        raise ValueError('Unsupported module')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open('a', encoding='utf-8', buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        sys.argv = [str(target), *args.arguments]
        runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__': main()
