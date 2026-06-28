# Создаю общий модуль для [[END_CALL]] регексов.
marker_module = '''"""Детектор платформенного маркера завершения разговора [[END_CALL]].

Единый контракт между LLM и backend:
  LLM выдаёт [[END_CALL]] в конце прощальной реплики,
  backend вырезает маркер до показа пользователю и поднимает флаг.

Используется в:
  - sentence_streamer: streaming voice-путь (парсинг по предложениям)
  - turn_orchestrator: text-режим и non-streaming voice-режим
"""
import re

# Основной регекс для полного маркера.
# Толерантен к вариантам: [[END_CALL]], [[end_call]], [[END-CALL]], [[ END_CALL ]], [[\\nEND_CALL\\n]].
_END_CALL_RE = re.compile(r\'\\[\\[\\s*END[\\s_-]*CALL\\s*\\]\\]\', re.IGNORECASE)

# Частичный маркер в конце buffer\'а (для streaming-пути и случаев когда
# LLM-stream разрезает маркер по SSE-чанкам между [[ и ]]).
_END_CALL_PARTIAL_RE = re.compile(
    r\'\\[\\[?\\s*(?:E(?:N(?:D[\\s_-]*(?:C(?:A(?:L(?:L\\s*\\]?)?)?)?)?)?)?)?\\s*$\',
    re.IGNORECASE,
)
'''

open('/home/ubuntu/voice-trainer/backend/app/services/end_call_marker.py', 'w', encoding='utf-8').write(marker_module)
print('Module created')

# Перевести sentence_streamer.py на импорт из общего модуля
p = '/home/ubuntu/voice-trainer/backend/app/services/sentence_streamer.py'
t = open(p, encoding='utf-8').read()

# Убрать локальное определение _END_CALL_RE и _END_CALL_PARTIAL_RE,
# добавить импорт
old = '''from app.services.tts_emotion_handlers import (
    _EMOTION_RE,
    select_emotion_handler,
)

# Платформенный маркер завершения разговора. Контракт между LLM и backend:
#   LLM выдаёт [[END_CALL]] на отдельной строке в конце прощальной реплики,
#   парсер вырезает его из текста перед TTS и чатом, поднимает флаг.
# Регекс толерантный: разные форматы ([[ end_call ]], [[\\nEND_CALL\\n]] и т.п.)
_END_CALL_RE = re.compile(r\'\\[\\[\\s*END[\\s_-]*CALL\\s*\\]\\]\', re.IGNORECASE)
# Частичный маркер в конце buffer\'а: от [ до [[END_CALL]
# Срабатывает когда LLM-stream разрезает маркер по опасным границам между SSE-чанками.
_END_CALL_PARTIAL_RE = re.compile(r\'\\[\\[?\\s*(?:E(?:N(?:D[\\s_-]*(?:C(?:A(?:L(?:L\\s*\\]?)?)?)?)?)?)?)?\\s*$\', re.IGNORECASE)'''

new = '''from app.services.tts_emotion_handlers import (
    _EMOTION_RE,
    select_emotion_handler,
)
from app.services.end_call_marker import _END_CALL_RE, _END_CALL_PARTIAL_RE'''

assert old in t, 'sentence_streamer regex anchor not found'
t = t.replace(old, new)
open(p, 'w', encoding='utf-8').write(t)
import ast; ast.parse(t)
print('sentence_streamer: now imports from end_call_marker')

# turn_orchestrator: тоже импорт из общего модуля
p2 = '/home/ubuntu/voice-trainer/backend/app/services/turn_orchestrator.py'
t2 = open(p2, encoding='utf-8').read()
old2 = 'from app.services.sentence_streamer import _END_CALL_RE  # единый регекс для voice+text'
new2 = 'from app.services.end_call_marker import _END_CALL_RE  # единый регекс для voice+text'
assert old2 in t2, 'turn_orchestrator import anchor not found'
t2 = t2.replace(old2, new2)
open(p2, 'w', encoding='utf-8').write(t2)
import ast; ast.parse(t2)
print('turn_orchestrator: now imports from end_call_marker (no more cross-layer dep)')
