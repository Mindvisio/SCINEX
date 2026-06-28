import json, re
from datetime import datetime

def parse_t(s):
    s = s.replace('Z', '+00:00')
    m = re.match(r'(.*T\d\d:\d\d:\d\d)\.(\d+)(\+.*)', s)
    if m:
        s = m.group(1) + '.' + (m.group(2)+'000000')[:6] + m.group(3)
    return datetime.fromisoformat(s)

data = json.load(open('/tmp/game_score.json'))
hits_b = [e for e in data if e.get('$type') == 'HitEvent']
t0 = parse_t([e for e in data if e.get('$type')=='GameStartEventV1'][0]['EventTime'])
bk = []
for h in hits_b:
    rel = (parse_t(h['EventTime']) - t0).total_seconds()
    dur = h.get('HitDurationInSeconds',0) or 0
    bk.append({'num': h['HitNumber'], 'start': rel-dur, 'scored': h['ScoreChanges'][0]['ScoreAdded']})

path = '/root/billman/archive/error_analysis_2026-06-14_legend_flotskaya/70c70b03_detection_log.json'
our = []
for line in open(path):
    line=line.strip()
    if not line: continue
    try: e=json.loads(line)
    except: continue
    if e.get('event') in ('hit_detected','hit_no_result'):
        our.append({'num': e.get('num_hit'), 'start': e.get('start_time',0), 'pot': e.get('balls_in_hole',0)})
our.sort(key=lambda x:x['start'])

# греди матч
used=set(); pairs=[]
for b in bk:
    best=None; bd=1e9
    for i,o in enumerate(our):
        if i in used: continue
        d=abs(o['start']-b['start'])
        if d<bd: bd=d; best=i
    if best is not None:
        used.add(best); pairs.append((b, our[best], bd))

print('=== СКОРИНГ НА 50 СОВПАВШИХ ПАРАХ (бэк ScoreAdded vs наш pot) ===')
agree=0; bk_more=0; our_more=0
bk_total=0; our_total=0
disagreements=[]
for b,o,d in pairs:
    bk_total += b['scored']; our_total += o['pot']
    if b['scored']==o['pot']:
        agree+=1
    elif b['scored']>o['pot']:
        bk_more+=1
        disagreements.append(('БЭК>НАШ', b, o, d))
    else:
        our_more+=1
        disagreements.append(('НАШ>БЭК', b, o, d))

print('  совпал скоринг: %d/50' % agree)
print('  бэк засчитал >, мы меньше: %d' % bk_more)
print('  мы засчитали >, бэк меньше: %d' % our_more)
print('  СУММА баллов на совпавших: бэк=%d / наш=%d' % (bk_total, our_total))
print('')
print('=== РАСХОЖДЕНИЯ СКОРИНГА ПОПАРНО ===')
for tag,b,o,d in disagreements:
    print('  %s  бэHit#%2d/нашShot#%2d  t≈%6.1fs  бэк+%d наш+%d  |Δstart|=%.1fs' % (
        tag, b['num'], o['num'], o['start'], b['scored'], o['pot'], d))
