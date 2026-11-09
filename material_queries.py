"""Storage-side transcript query for reviewed notes."""
import datetime as dt
import hashlib
import json
from pathlib import Path


def read(file, default=None):
    try: return json.loads(Path(file).read_text(encoding='utf-8-sig'))
    except FileNotFoundError: return {} if default is None else default


def collect(root, since, processed, limit=24, cache=None, require_review=False):
    from transcript_corrections import effective, load
    from transcript_quality import suspected_prompt_echo
    cache = {} if cache is None else cache
    corrections = load(root); sources = set()
    for day in (dt.datetime.now(), dt.datetime.now()-dt.timedelta(days=1)):
        name = day.strftime('%Y%m%d'); sources.add(root/'out'/name/'timeline.jsonl')
        sources.add(root/'out'/('cloud-asr-'+name)/'timeline.jsonl')
        sources.update((root/'out').glob('cloud-asr-*/'+name+'/timeline.jsonl'))
    from material_exchange import MaterialExchange
    exchange = MaterialExchange(root)
    for record in corrections.get('records', {}).values():
        if record.get('revision', 0) > 0:
            try: sources.add(exchange.transcript_source(record['sourceFile'], allow_relocated=True))
            except (ValueError, KeyError): continue
    correction_file=root/'transcript-corrections.json'; revision=correction_file.stat().st_mtime_ns if correction_file.exists() else 0
    for old in set(cache)-{str(source) for source in sources}:del cache[old]
    grouped={}
    # Local history remains available when the user switches to cloud; prefer its higher-quality version per WAV.
    for source in sorted(sources, key=lambda p: (p.relative_to(root/'out').parts[0].startswith('cloud-asr-') if p.is_relative_to(root/'out') else False, str(p))):
        if not source.resolve().is_relative_to((root/'out').resolve()) or not source.exists():continue
        stamp=(source.stat().st_mtime_ns,source.stat().st_size,revision,since)
        item=cache.get(str(source))
        if not item or item['stamp']!=stamp:
            parsed=[]
            with source.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row=json.loads(line)
                        if float(row.get('ts',0))>=since-90 and row.get('text','').strip():
                            current=effective(row,source,corrections)
                            if not suspected_prompt_echo(current.get('text','')):parsed.append(current)
                    except (ValueError,TypeError,KeyError):continue
            item={'stamp':stamp,'rows':parsed};cache[str(source)]=item
        by_file={}
        for row in item['rows']:by_file.setdefault(str(row.get('file','')),[]).append(row)
        for file,parts in by_file.items():
            first=parts[0];text='\n'.join(part['text'] for part in parts)
            grouped[file]={'key':file,'file':file,'hash':hashlib.sha256(text.encode()).hexdigest(),'text':text,'t':first.get('t'),
                'date':first.get('date'),'start':min(p['start'] for p in parts),'end':max(p['end'] for p in parts),'source':str(source)}
    rows = [row for row in sorted(grouped.values(),key=lambda r:(r['file'],r['start'])) if processed.get(row['key'])!=row['hash']]
    if require_review:
        reviews=read(root/'subtitle-reviews.json',{'items':{}}).get('items',{})
        rows=[row for row in rows if reviews.get(row['key'],{}).get('status')=='screened' and reviews[row['key']].get('hash')==row['hash'] and Path(reviews[row['key']].get('source','')).resolve()==Path(row['source']).resolve()]
    return rows[:limit]
