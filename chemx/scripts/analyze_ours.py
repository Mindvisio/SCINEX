import json

path = '/root/billman/archive/error_analysis_2026-06-14_legend_flotskaya/70c70b03_detection_log.json'
events = []
for line in open(path):
    line = line.strip()
    if line:
        try:
            events.append(json.loads(line))
        except:
            pass

# Финальное событие
fin = [e for e in events if e.get('event') == 'detection_finished']
fin = fin[0] if fin else None

# Все hit_detected с забитыми
hits = [e for e in events if e.get('event') == 'hit_detected']
no_result = [e for e in events if e.get('event') == 'hit_no_result']

print('=== OUR DETECTOR ===')
print('  hit_detected: %d' % len(hits))
print('  hit_no_result: %d' % len(no_result))

potted = [h for h in hits if h.get('balls_in_hole', 0) > 0]
print('  из них с забитым шаром (balls_in_hole>0): %d' % len(potted))
print('')
print('=== РЕЗУЛЬТАТИВНЫЕ УДАРЫ (наш детектор) ===')
total_potted = 0
for h in potted:
    bih = h['balls_in_hole']
    total_potted += bih
    print('  Shot#%2d  t=%6.1f-%5.1fs  +%dball  remaining=%d  disp=%.1f' % (
        h.get('num_hit', 0), h.get('start_time', 0), h.get('end_time', 0),
        bih, h.get('remaining', -1), h.get('total_disp', 0)))

if fin:
    print('')
    print('OUR TOTALS (detection_finished):')
    print('  num_of_hits: %d' % fin.get('num_of_hits', 0))
    print('  num_of_hits_with_result: %d' % fin.get('num_of_hits_with_result', 0))
    print('  num_of_hits_no_result: %d' % fin.get('num_of_hits_no_result', 0))
    print('  final_confirmed (remaining): %d' % fin.get('final_confirmed', -1))
    print('  СУММА забитых шаров: %d' % total_potted)
    nb = fin.get('num_of_balls_each_hit', [])
    if nb:
        print('  шаров в начале: %d, в конце: %d' % (nb[0], nb[-1]))

json.dump({'potted': [[h.get('num_hit'), h.get('start_time'), h.get('end_time'), h['balls_in_hole'], h.get('remaining')] for h in potted],
           'total_potted': total_potted,
           'fin': fin}, open('/tmp/ours_summary.json', 'w'))
