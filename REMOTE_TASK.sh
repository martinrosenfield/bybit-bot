#!/bin/bash
# REMOTE_TASK.sh — плановая проверка dry-run лога Bybit-бота (Kimi, 15.10). Только чтение.
LOG="logs/bot.log"

echo "=== 1. ПРОЦЕСС (два замера за 8 сек) ==="
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"
sleep 8
echo "--- повторный замер (у живого бота CPU-time растёт) ---"
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"

echo "=== 2. ФАЙЛЫ ЛОГОВ ==="
ls -lt logs/ 2>/dev/null | head -8 || echo "папки logs/ нет"
[ -f "$LOG" ] && stat -f "bot.log изменён: %Sm" "$LOG" || echo "bot.log НЕ НАЙДЕН"
date '+сейчас на Mac: %Y-%m-%d %H:%M:%S %Z'

echo "=== 3. РЕЖИМ ==="
grep -E '"dry_run"|"symbols"|"atr_stop_mult"|"atr_tp_mult"|"taker_fee_rate"|"risk_per_trade"' config.json 2>/dev/null
echo "--- md5 кода и конфига ---"
md5 -q bybit_bot.py config.json 2>/dev/null

if [ -f "$LOG" ]; then
  START=$(grep -n "PREFLIGHT" "$LOG" | tail -1 | cut -d: -f1)
  [ -z "$START" ] && START=1
  echo "=== 4. ЗАПУСК (лог считаем со строки $START) ==="
  awk -v s="$START" 'NR>=s && NR<=s+2' "$LOG"

  echo "=== 5. СЧЁТЧИКИ С МОМЕНТА ЗАПУСКА ==="
  SEG=$(awk -v s="$START" 'NR>=s' "$LOG")
  echo "всего строк: $(printf '%s\n' "$SEG" | wc -l | tr -d ' ')"
  echo "строк bar=: $(printf '%s\n' "$SEG" | grep -c 'bar=')"
  echo "сигналов DRY-RUN: $(printf '%s\n' "$SEG" | grep -c 'DRY-RUN')"
  echo "входов [DRY] (старый формат): $(printf '%s\n' "$SEG" | grep -c '\[DRY\]')"
  echo "пропусков SIGNAL SKIPPED: $(printf '%s\n' "$SEG" | grep -c 'SIGNAL SKIPPED')"
  echo "сигналов SIGNAL Buy/Sell: $(printf '%s\n' "$SEG" | grep -cE 'SIGNAL (Buy|Sell)')"
  echo "входов LIVE-DEMO: $(printf '%s\n' "$SEG" | grep -c 'LIVE-DEMO')"
  echo "ошибок (ERROR/Traceback/сеть): $(printf '%s\n' "$SEG" | grep -cE 'ERROR|Traceback|FailedRequestError|ConnectionError|ReadTimeout|loop error')"
  echo "дневных стопов: $(printf '%s\n' "$SEG" | grep -c 'DAILY LOSS')"

  echo "=== 6. СИГНАЛЫ / ПРОПУСКИ / ОШИБКИ (все с запуска) ==="
  printf '%s\n' "$SEG" | grep -E 'SIGNAL|DRY|LIVE-DEMO|ERROR|Traceback|FailedRequestError|ConnectionError|ReadTimeout|loop error|DAILY LOSS' | tail -80

  echo "=== 7. SNAPSHOT И ХВОСТ ==="
  printf '%s\n' "$SEG" | grep -i 'snapshot' | tail -3
  echo "--- последние 8 строк лога ---"
  tail -8 "$LOG"
fi

echo "=== 8. bot.out ==="
tail -5 bot.out 2>/dev/null || echo "bot.out не найден"

echo "=== 9. СОБЫТИЯ JSONL (вчера + сегодня, UTC) ==="
TODAY=$(date -u +%F)
YEST=$(date -u -v-1d +%F 2>/dev/null || date -u -d 'yesterday' +%F)
for d in "$YEST" "$TODAY"; do
  f="logs/events_${d}.jsonl"
  if [ -f "$f" ]; then echo "--- $f ---"; cat "$f"; else echo "нет $f"; fi
done

echo "=== 10. ОТЧЁТ ПО API ==="
if [ -n "$BYBIT_API_KEY" ]; then
  python3 bybit_report.py 2>&1 | head -50
else
  echo "ключей в env нет — API-отчёт пропущен (норма для REMOTE_RUN)"
fi
