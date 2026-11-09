"""Apply subtitle corrections through the material boundary."""
from pathlib import Path
import re
from transcript_corrections import apply_manual_text, publish_reviewed, CorrectionConflict


def correct(root, item, expected_version, replacement):
    location = re.fullmatch(r'line:([1-9][0-9]*)', str(item.get('locator') or ''))
    if not location:
        raise ValueError('字幕位置无效')
    source = (Path(root) / item['source']).resolve()
    result = apply_manual_text(root, source, int(location.group(1)), expected_version, replacement)
    warnings = []
    if result['changed']:
        try:
            publish_reviewed(source, root)
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append('修订已保存，但修订稿刷新失败')
        try:
            from classroom_materials import publish
            publish(source.parent, root=root)
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append('修订已保存，但课堂材料刷新失败')
    return result, warnings
