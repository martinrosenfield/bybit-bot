#!/bin/bash
# REMOTE_TASK.sh — сверка локальных правок с репо + API-сверка позиций (Kimi, 18.10). Только чтение.
# Контекст: в working tree изменены bybit_bot.py и test_trade_guards.py без коммита — нужен полный diff.

echo "=== 1. git status и diff --stat ==="
git status --short
git diff --stat
echo "--- md5 рабочих файлов vs HEAD ---"
md5 -q bybit_bot.py config.json 2>/dev/null
git show HEAD:bybit_bot.py | md5 -q
git show HEAD:config.json | md5 -q 2>/dev/null || echo "config.json в HEAD отсутствует"

echo "=== 2. ПОЛНЫЙ diff bybit_bot.py ==="
git diff bybit_bot.py

echo "=== 3. ПОЛНЫЙ diff test_trade_guards.py ==="
git diff test_trade_guards.py

echo "=== 4. diff config.json (если есть) ==="
git diff config.json

echo "=== 5. Недобавленные файлы (Codex?) — даты и первые строки ==="
for f in CHECK_*.md restore_demo_bot.py start_demo.command restart_demo.command backtest_comparison.py BACKTEST_COMPARISON.json BACKTEST_COMPARISON.md test_restore_demo_bot.py; do
  if [ -f "$f" ]; then
    echo "--- $f (изменён $(stat -f '%Sm' "$f")) ---"
    head -20 "$f"
  fi
done

echo "=== 6. ПРОЦЕСС (два замера за 10 сек) ==="
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"
sleep 10
ps -eo pid,lstart,time,%cpu,command | grep -i "[b]ybit" || echo "ПРОЦЕСС НЕ НАЙДЕН"

echo "=== 7. Хвост bot.log и managed_console.log ==="
tail -10 logs/bot.log 2>/dev/null
echo "--- managed_console.log ---"
tail -10 managed_console.log 2>/dev/null || echo "нет"

echo "=== 8. СОБЫТИЯ СЕГОДНЯ (UTC) ==="
f="logs/events_$(date -u +%F).jsonl"
[ -f "$f" ] && cat "$f" || echo "нет $f"

echo "=== 9. ПОЗИЦИИ / ОРДЕРА (нужны РЕАЛЬНЫЕ ключи в env) ==="
KEY_OK=1
case "$BYBIT_API_KEY" in *[!A-Za-z0-9_-]*) KEY_OK=0;; "" ) KEY_OK=0;; esac
case "$BYBIT_API_SECRET" in *[!A-Za-z0-9_-]*) KEY_OK=0;; "" ) KEY_OK=0;; esac
if [ "$KEY_OK" = "1" ]; then
python3 - <<'EOF' 2>&1 | grep -v NotOpenSSLWarning | grep -v warnings.warn
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
print("--- WALLET (totalEquity USDT) ---")
for a in (wal.get("result") or {}).get("list") or []:
    print(a.get("totalEquity"))
EOF
else
  echo "КЛЮЧИ НЕ ЗАДАНЫ или содержат недопустимые символы (проверьте: не вставили ли вы буквально 'ВАШ_КЛЮЧ')."
  echo "Выполните в ТОМ ЖЕ окне терминала с РЕАЛЬНЫМИ значениями:"
  echo '  export BYBIT_API_KEY=... && export BYBIT_API_SECRET=...'
  echo "и только потом: bash REMOTE_RUN.sh"
fi
