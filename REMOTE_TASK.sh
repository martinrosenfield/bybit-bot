#!/bin/bash
# REMOTE_TASK.sh — коммит верифицированного diff Codex в main (Kimi, 18.10). Решение Дмитрия: КОММИТИТЬ.
# Порядок: offline-тесты → (только при успехе) commit bybit_bot.py + test_trade_guards.py → push.
# Ничего другое не коммитить. Бот НЕ перезапускать (процесс уже исполняет этот код).

cd "$(dirname "$0")"

echo "=== 1. СОСТОЯНИЕ ДО ==="
git status --short
git log --oneline -2

echo "=== 2. OFFLINE-ТЕСТЫ ==="
T1=0; T2=0
python3 -m unittest test_trade_guards -v 2>&1 && T1=1 || echo "ТЕСТЫ test_trade_guards НЕ ПРОШЛИ"
python3 -m unittest test_restore_demo_bot -v 2>&1 && T2=1 || echo "ТЕСТЫ test_restore_demo_bot НЕ ПРОШЛИ (файл может отсутствовать — см. вывод)"

if [ "$T1" = "1" ] && [ "$T2" = "1" ]; then
  echo "=== 3. КОММИТ И PUSH ==="
  git add bybit_bot.py test_trade_guards.py
  git commit -m "Verification loop v2: tolerate transient API errors, strict reconciled_after_retry fallback with exact SL/TP checks, caffeinate sleep guard, READY event

Authored by Codex on the Mac (15-16.10), reviewed by Kimi 18.10: risk parameters untouched; running PID 21853 already executes this code (ETHUSDT ENTRY 16.10 used the fallback). Tests: +14 fallback mismatch cases." \
  && git push \
  && echo "PUSH OK" \
  || echo "КОММИТ/PUSH НЕ УДАЛСЯ — НИЧЕГО НЕ ПЕРЕЗАПУСКАТЬ, прислать вывод Kimi"
else
  echo "=== КОММИТ ОТМЕНЁН: тесты не прошли. ==="
fi

echo "=== 4. СОСТОЯНИЕ ПОСЛЕ ==="
git status --short
git log --oneline -2

echo "=== 5. ПРОВЕРКИ ==="
echo "--- процесс бота ---"
ps -eo pid,lstart,time,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"
echo "--- caffeinate ---"
pgrep -x caffeinate >/dev/null && ps -eo pid,command | grep "[c]affeinate" || echo "caffeinate НЕ НАЙДЕН"
echo "--- хвост bot.log ---"
tail -5 logs/bot.log 2>/dev/null
