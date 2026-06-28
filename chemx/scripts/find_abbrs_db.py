#!/usr/bin/env python3
import re
import collections
import subprocess

result = subprocess.run(
    ['docker', 'exec', 'voice-trainer-postgres-1', 'psql', '-U', 'trainer', '-d', 'trainer',
     '-t', '-c', "SELECT content FROM messages WHERE role='assistant'"],
    capture_output=True, text=True, timeout=10
)
text = result.stdout
matches = re.findall(r'\b[А-ЯЁ]{2,6}\b', text)
c = collections.Counter(matches)
print('=== UPPERCASE CYRILLIC IN CFO REPLIES ===')
for abbr, count in c.most_common(30):
    print(f'{count:4d}  {abbr}')