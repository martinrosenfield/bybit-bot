#!/bin/bash
# REMOTE_TASK.sh — проверка живости бота и состояния счёта (Kimi, 18.10). Только чтение.
# Цель: подтвердить непрерывность 16–18.10 и проверить две позиции инцидента 15.10 18:30.
LOG="logs/bot.log"

echo "=== 1. ПРОЦЕСС (два замера за 8 сек) ==="
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"
sleep 8
echo "--- повторный замер (у живого бота CPU-time растёт) ---"
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"

echo "=== 2. СВЕЖЕСТЬ ЛОГА ==="
ls -lt logs/ 2>/dev/null | head -8 || echo "папки logs/ нет"
[ -f "$LOG" ] && stat -f "bot.log изменён: %Sm" "$LOG" || echo "bot.log НЕ НАЙДЕН"
date '+сейчас на Mac: %Y-%m-%d %H:%M:%S %Z'

echo "=== 3. РЕЖИМ И КОД ==="
grep -E '"dry_run"|"entries_paused"|"symbols"|"atr_stop_mult"|"atr_tp_mult"|"taker_fee_rate"|"risk_per_trade"' config.json 2>/dev/null
echo "--- md5 кода и конфига ---"
md5 -q bybit_bot.py config.json 2>/dev/null
echo "--- соответствие main репо ---"
git log --oneline -1

if [ -f "$LOG" ]; then
  START=$(grep -n "PREFLIGHT" "$LOG" | tail -1 | cut -d: -f1)
  [ -z "$START" ] && START=1
  echo "=== 4. ПОСЛЕДНИЙ ЗАПУСК (лог считаем со строки $START) ==="
  awk -v s="$START" 'NR>=s && NR<=s+2' "$LOG"

  echo "=== 5. СЧЁТЧИКИ С МОМЕНТА ЗАПУСКА ==="
  SEG=$(awk -v s="$START" 'NR>=s' "$LOG")
  echo "всего строк: $(printf '%s\n' "$SEG" | wc -l | tr -d ' ')"
  echo "строк bar=: $(printf '%s\n' "$SEG" | grep -c 'bar=')"
  echo "сигналов SIGNAL Buy/Sell: $(printf '%s\n' "$SEG" | grep -cE 'SIGNAL (Buy|Sell)')"
  echo "входов LIVE-DEMO: $(printf '%s\n' "$SEG" | grep -c 'LIVE-DEMO')"
  echo "строк planned_risk: $(printf '%s\n' "$SEG" | grep -c 'planned_risk')"
  echo "ACTION_REQUIRED: $(printf '%s\n' "$SEG" | grep -c 'ACTION_REQUIRED')"
  echo "пропусков SIGNAL SKIPPED: $(printf '%s\n' "$SEG" | grep -c 'SIGNAL SKIPPED')"
  echo "дневных стопов: $(printf '%s\n' "$SEG" | grep -c 'DAILY LOSS')"
  echo "ошибок (ERROR/Traceback/сеть): $(printf '%s\n' "$SEG" | grep -cE 'ERROR|Traceback|FailedRequestError|ConnectionError|ReadTimeout|loop error')"

  echo "=== 6. ВХОДЫ / ACTION_REQUIRED / ОШИБКИ / DAILY LOSS (с запуска) ==="
  printf '%s\n' "$SEG" | grep -E 'LIVE-DEMO|ACTION_REQUIRED|SIGNAL (Buy|Sell)|ERROR|Traceback|FailedRequestError|ConnectionError|ReadTimeout|loop error|DAILY LOSS' | tail -120

  echo "=== 7. SNAPSHOT И ХВОСТ ==="
  printf '%s\n' "$SEG" | grep -i 'snapshot' | tail -3
  echo "--- последние 8 строк лога ---"
  tail -8 "$LOG"
fi

echo "=== 8. СОСТОЯНИЕ РАНТАЙМА ==="
for f in runtime_state.json state.json baseline.json; do
  [ -f "$f" ] && { echo "--- $f ---"; cat "$f"; } || echo "$f нет"
done

echo "=== 9. СОБЫТИЯ JSONL (последние 4 дня, UTC) ==="
for d in $(date -u -v-3d +%F 2>/dev/null || date -u -d '3 days ago' +%F) $(date -u -v-2d +%F 2>/dev/null || date -u -d '2 days ago' +%F) $(date -u -v-1d +%F 2>/dev/null || date -u -d 'yesterday' +%F) $(date -u +%F); do
  f="logs/events_${d}.jsonl"
  if [ -f "$f" ]; then echo "--- $f ---"; cat "$f"; else echo "нет $f"; fi
done

echo "=== 10. bot.out ==="
tail -5 bot.out 2>/dev/null || echo "bot.out не найден"

echo "=== 11. ПОЗИЦИИ И ОРДЕРА (demo API, если ключи в env) ==="
if [ -n "$BYBIT_API_KEY" ] && [ -n "$BYBIT_API_SECRET" ]; then
python3 - <<'EOF' 2>&1
import json, os
from pybit.unified_trading import HTTP
s = HTTP(testnet=True, api_key=os.environ["BYBIT_API_KEY"], api_secret=os.environ["BYBIT_API_SECRET"])
pos = s.get_positions(category="linear", settleCoin="USDT")
print("--- POSITIONS ---")
for p in (pos.get("result") or {}).get("list") or []:
    if float(p.get("size") or 0) > 0:
        print(json.dumps({k: p.get(k) for k in ("symbol","side","size","avgPrice","markPrice","stopLoss","takeProfit","unrealisedPnl","createdTime")}, ensure_ascii=False))
ords = s.get_open_orders(category="linear", settleCoin="USDT")
print("--- OPEN ORDERS ---")
for o in (ords.get("result") or {}).get("list") or []:
    print(json.dumps({k: o.get(k) for k in ("symbol","orderType","side","qty","price","stopOrderType","orderStatus","createdTime")}, ensure_ascii=False))
wal = s.get_wallet_balance(accountType="UNIFIED")
print("--- WALLET (equity USDT) ---")
for a in (wal.get("result") or {}).get("list") or []:
    print(a.get("totalEquity"))
EOF
else
  echo "ключей в env нет — API-проверка пропущена."
  echo "Чтобы включить её, перед запуском REMOTE_RUN выполните в ТОМ ЖЕ окне терминала:"
  echo '  export BYBIT_API_KEY=... && export BYBIT_API_SECRET=...'
  echo "и только потом: bash REMOTE_RUN.sh"
fi
