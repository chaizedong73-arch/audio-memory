"""Semantic control operations for the optional workbench interface."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
import classroom_mode
import notes_maintenance


def execute(root, action, value=None):
    root = Path(root).resolve()
    if not root.is_dir(): raise ValueError('录音项目未连接')
    def owned(name):
        path = root / name
        if not path.resolve().is_relative_to(root): raise ValueError('配置位置无效')
        return path
    value = value or {}
    if action == 'classroom-read':
        owned('classroom-mode.json')
        return classroom_mode.enabled(root)
    if action == 'classroom-set':
        owned('classroom-mode.json'); owned('notes-maintenance.json')
        if type(value.get('enabled')) is not bool: raise ValueError('课堂模式参数无效')
        return classroom_mode.set_enabled(root,value['enabled'])
    if action in ('notes-read','notes-save'):
        path=owned('notes-maintenance.json')
        if action == 'notes-read': return notes_maintenance.read(path)
        if not isinstance(value,dict): raise ValueError('笔记设置无效')
        if value.get('enabled'):
            owned('classroom-mode.json'); classroom_mode.require(root); notes_maintenance.validate(value)
        notes_maintenance.save(path,value);return value
    if action in ('subtitle-read','subtitle-save'):
        path=owned('subtitle-maintenance.json')
        if action == 'subtitle-read': return notes_maintenance.read(path)
        if not isinstance(value,dict): raise ValueError('字幕设置无效')
        notes_maintenance.save(path,value);return value
    if action == 'transcription-read':
        return notes_maintenance.read(owned('transcription-control.json'))
    if action == 'transcription-set':
        mode=value.get('mode')
        if mode not in ('local','cloud'): raise ValueError('未知转写方式')
        now=time.time();state={'mode':mode,'generation':uuid.uuid4().hex,'startedAt':now,'deadline':now+10800,'budgetYuan':5}
        notes_maintenance.save(owned('transcription-control.json'),state);return state
    if action.startswith('camera-'):
        import scene_client
        if action == 'camera-exists': return scene_client.exists(root)
        if action == 'camera-owner': return scene_client.owner_pid(root)
        if action == 'camera-slides': return scene_client.slides_directory(root)
        if action == 'camera-call': return scene_client.call(root,value.get('path'),value.get('body'))
    if action == 'context-path':
        from context_auto import candidate_path
        return str(candidate_path(root))
    if action == 'notes-job':
        return notes_maintenance.dispatch_state(value.get('hostRoot',''),value.get('job',''))
    raise ValueError('未知工作台操作')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--action',required=True)
    args=parser.parse_args()
    try:
        value=json.load(sys.stdin) if args.action.endswith(('-set','-save')) or args.action in ('camera-call','notes-job') else {}
        print(json.dumps(execute(args.root,args.action,value),ensure_ascii=False))
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
