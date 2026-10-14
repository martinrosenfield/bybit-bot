#!/bin/bash
# REMOTE_TASK.sh — задача от Kimi. Только чтение/диагностика, ничего не меняет.
echo "--- процесс бота ---"
ps aux | grep -i bybit_bot | grep -v grep || echo "ПРОЦЕСС НЕ НАЙДЕН"
echo "--- config.json ---"
cat config.json 2>/dev/null
echo "--- версия кода (md5) ---"
md5 -q bybit_bot.py config.json 2>/dev/null
echo "--- синтаксис ---"
python3 -c "import ast; ast.parse(open('bybit_bot.py').read()); print('syntax OK')" 2>&1
echo "--- лог (последние 80 строк) ---"
tail -80 logs/bot.log 2>/dev/null || echo "лог не найден"
echo "--- события сегодня (UTC) ---"
TODAY=$(date -u +%F)
cat "logs/events_${TODAY}.jsonl" 2>/dev/null || { echo "нет файла за $TODAY, вот что есть:"; ls -la logs/ 2>/dev/null; }
echo "--- дневной отчёт ---"
python3 bybit_report.py 2>&1 | head -100
