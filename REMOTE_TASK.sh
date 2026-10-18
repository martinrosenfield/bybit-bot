#!/bin/bash
# REMOTE_TASK.sh — промежуточный статус бота (Kimi, 18.10.2026 ~14:05 МСК).
# ТОЛЬКО ЧТЕНИЕ: процессы, свежесть логов, сделки за сегодня, ошибки, MT5.
BOT="$HOME/Documents/ChatGPT/Трейдинг/bybit-bot"
cd "$BOT" 2>/dev/null || { echo "!!! bot dir not found: $BOT"; exit 1; }

echo "--- time (локальное на Mac) ---"
date '+%Y-%m-%d %H:%M:%S %Z'

echo
echo "--- процессы: python / bybit_bot / caffeinate ---"
pgrep -fl python || echo "!!! python processes: none"
ps aux | grep -iE "caffeinate|bybit_bot" | grep -v grep || echo "no caffeinate/bybit match"

echo
echo "--- рост CPU-time (две выборки с паузой 10 c) ---"
PID=$(pgrep -f bybit_bot.py | head -1)
if [ -n "$PID" ]; then
  ps -o pid,etime,%cpu,time -p "$PID"
  sleep 10
  echo "  ...через 10 сек..."
  ps -o pid,etime,%cpu,time -p "$PID"
else
  echo "!!! bybit_bot.py НЕ ЗАПУЩЕН"
fi

echo
echo "--- состояние репо и конфиг ---"
git log --oneline -1
grep -E '"dry_run"|"entries_paused"|"risk_per_trade"|"leverage"' config.json || true

echo
echo "--- свежесть логов ---"
ls -lt logs/ | head -8

echo
echo "--- bot.log, последние 30 строк ---"
tail -30 logs/bot.log 2>/dev/null || echo "!!! bot.log отсутствует"

echo
echo "--- события за сегодня (ENTRY/закрытия) ---"
TODAY=$(date +%Y-%m-%d)
if [ -f "logs/events_${TODAY}.jsonl" ]; then
  grep -E "ENTRY|EXIT|closed|TP|SL" "logs/events_${TODAY}.jsonl" | tail -25
  echo "-- всего строк в events за сегодня: $(wc -l < "logs/events_${TODAY}.jsonl")"
else
  echo "нет файла events_${TODAY}.jsonl (возможно, событий ещё не было)"
fi

echo
echo "--- ошибки в bot.log (последние 15) ---"
grep -E "ERROR|RuntimeError|FailedRequest|403|ReadTimeout|ConnectionError" logs/bot.log 2>/dev/null | tail -15 || echo "ошибок в логе не найдено"

echo
echo "--- MT5 (wine) быстрая проверка ---"
ps aux | grep -iE "metatrader|wine" | grep -v grep | head -5 || echo "MT5 не запущен"

echo
echo "--- аптайм / нагрузка ---"
uptime
