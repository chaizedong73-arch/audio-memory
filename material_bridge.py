"""Bridge saved files to the local material index without controlling producers."""
from data_location import data_root as default_data_root
import argparse
import json
from pathlib import Path
import time

from material_store import register_material, update_module

ROOT = Path(__file__).resolve().parent


def sync(root=ROOT, visual_only=False, stop_file=None, exchange=None):
    root = Path(root).resolve()
    report = {'audio': 0, 'transcript': 0, 'slides': 0, 'ocr': 0, 'alignment': 0, 'feedback': 0, 'errors': []}
    from material_ingest import ingest_recordings_and_transcripts
    ingestion = ingest_recordings_and_transcripts(root, visual_only=visual_only, register=register_material, exchange=exchange)
    report['audio'] = ingestion['audio']
    report['transcript'] = ingestion['transcript']
    report['errors'].extend(ingestion['errors'])
    from material_ingest import ingest_visual_and_feedback
    ingestion = ingest_visual_and_feedback(root, visual_only=visual_only, stop_file=stop_file, register=register_material, exchange=exchange)
    for kind in ('slides', 'ocr', 'alignment', 'feedback'):
        report[kind] = ingestion[kind]
    report['errors'].extend(ingestion['errors'])
    try:
        update_module('material_bridge_visual' if visual_only else 'material_bridge', 'error' if report['errors'] else 'ready',
                      f"audio={report['audio']}, transcript={report['transcript']}, slides={report['slides']}, ocr={report['ocr']}, alignment={report['alignment']}, feedback={report['feedback']}, errors={len(report['errors'])}", root)
    except InterruptedError:
        raise
    except Exception:
        # A broken database must not stop the independent recording process.
        report['errors'].append({'source': 'material-database', 'kind': 'StatusUnavailable'})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Index saved audio and transcript files')
    parser.add_argument('--root', type=Path, default=default_data_root())
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    while True:
        result = sync(args.root)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not args.watch or (args.stop_file and args.stop_file.exists()):
            raise SystemExit(1 if result['errors'] else 0)
        for _ in range(50):
            if args.stop_file and args.stop_file.exists(): break
            time.sleep(.2)
