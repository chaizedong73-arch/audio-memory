"""Private per-attempt ledger. Amounts are estimates, never provider bills."""
import datetime as dt
import json
import math
from pathlib import Path
import uuid

PRICE_SOURCE = 'https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1'


class UsageRecordingError(OSError):
    """Do not repeat a paid request just because its ledger could not be written."""


def record_usage(root, *, file, model, protocol, duration, result=None, error=None, official=False):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    usage = result.get('usage') if isinstance(result, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    def count(*keys):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                return value
        return None
    prompt, completion = count('prompt_tokens', 'input_tokens'), count('completion_tokens', 'output_tokens')
    amount = None
    # Count all prompt tokens at the audio rate, ignoring cache discounts.
    # This is an upper estimate; mixed text/audio usage is not an exact bill.
    if official and protocol == 'ark_audio' and model == 'doubao-seed-2-0-mini-260428' and prompt is not None and completion is not None and prompt <= 32000:
        amount = round((prompt * 6 + completion * 4) / 1_000_000, 8)
    row = {'id': uuid.uuid4().hex, 'time': now.isoformat(timespec='seconds'), 'date': now.date().isoformat(),
           'file': Path(file).name, 'model': model, 'protocol': protocol, 'audioSeconds': round(duration, 3),
           'status': 'error' if error else 'response', 'errorType': type(error).__name__ if error else None,
           'requestId': result.get('id') if isinstance(result, dict) and isinstance(result.get('id'), str) else None,
           'inputTokens': prompt, 'outputTokens': completion, 'estimatedYuan': amount,
           'pricing': 'audio_rate_upper_estimate' if amount is not None else 'unknown',
           'priceSource': PRICE_SOURCE if amount is not None else None, 'priceChecked': '2026-11-06' if amount is not None else None}
    target = Path(root) / 'out' / 'cloud-usage' / (row['date'] + '.jsonl')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError as exc:
        raise UsageRecordingError('费用记录写入失败；该请求不自动重试，避免重复扣费') from exc
    return row
