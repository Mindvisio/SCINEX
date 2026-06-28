#!/usr/bin/env python3
import re
import collections
import sys
import os

scenarios_dir = '/home/ubuntu/voice-trainer/backend/scenarios'
all_text = ''
for fn in os.listdir(scenarios_dir):
    if fn.endswith('.yaml'):
        with open(os.path.join(scenarios_dir, fn), 'r', encoding='utf-8') as f:
            all_text += f.read() + '\n'

# All-caps Cyrillic 2-6 chars
matches = re.findall(r'\b[А-ЯЁ]{2,6}\b', all_text)
c = collections.Counter(matches)
print('=== TOP UPPERCASE CYRILLIC TOKENS IN SCENARIOS ===')
for abbr, count in c.most_common(40):
    print(f'{count:4d}  {abbr}')