"""Evidence-first vocabulary: immutable observations and conservative spatial groups."""
import hashlib
import re

def build_structure(words, image_hash, model, width, height):
    page_id = 'page-' + image_hash
    observations = [dict(item, id=f'o{i:05d}', pageId=page_id,
                         provenance={'model': model, 'index': i},
                         verification='unverified') for i, item in enumerate(words)]
    lines = []
    for item in sorted((o for o in observations if o['bbox']), key=lambda o: (o['bbox'][1], o['bbox'][0])):
        x, y, w, h = item['bbox']
        candidates = [line for line in lines if min(y+h, line['bottom'])-max(y, line['top']) >= .55*min(h, line['height'])]
        if candidates:
            line = min(candidates, key=lambda line: abs(y+h/2-line['center']))
            line['items'].append(item)
        else:
            lines.append(dict(items=[item], top=y, bottom=y+h, height=h, center=y+h/2))
    groups = []
    def emit(items):
        if not items:
            return
        text = ''
        for item in items:
            value = item['text']
            # Chinese OCR tokens concatenate; Latin tokens retain word boundaries.
            if text and re.search(r'[A-Za-z0-9]$', text) and re.match(r'[A-Za-z0-9]', value):
                text += ' '
            text += value
        boxes = [o['bbox'] for o in items]
        box = None
        if all(boxes):
            x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
            box=[x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]
        ids=[o['id'] for o in items]
        groups.append(dict(id='g-'+hashlib.sha256('|'.join(ids).encode()).hexdigest()[:16],
                           pageId=page_id, text=text, kind='空间行组', bbox=box,
                           observationIds=ids, method='horizontal-overlap-gap-v1',
                           uncertain=True, verification='unverified',
                           interpretation=None))
    if model != 'local:windows':
        for item in observations:
            emit([item])
            groups[-1]['method']='model-token-order-v1'
            groups[-1]['kind']='模型词组'
        lines=[]
    for line in sorted(lines, key=lambda line: (line['top'], min(o['bbox'][0] for o in line['items']))):
        current=[]
        for item in sorted(line['items'],key=lambda o:o['bbox'][0]):
            if current:
                prior=current[-1]['bbox'];box=item['bbox']
                # Compare physical pixels, because normalized x/y use different scales.
                gap=(box[0]-prior[0]-prior[2])*width/1000
                if gap > 1.5*max(prior[3],box[3])*height/1000:
                    emit(current);current=[]
            current.append(item)
        emit(current)
    for item in observations:
        if model == 'local:windows' and item['bbox'] is None:
            emit([item])
    return dict(page={'id':page_id,'imageHash':image_hash,'width':width,'height':height,
                      'coordinateSystem':'normalized-1000-xywh','scope':'single-page'},
                observations=observations, groups=groups, concepts=[],
                relations=[dict(type='contains',sourceId=g['id'],targetId=o,
                                evidenceIds=[o],status='derived-spatial')
                           for g in groups for o in g['observationIds']],
                readingText='\n'.join(g['text'] for g in groups),
                limitations=['Horizontal layout heuristic; columns, superscripts and formulas require review.',
                             'No semantic equivalence or OCR confidence is inferred.'])
