#!/bin/bash
# REMOTE_RUN.sh — удалённый запуск команд Kimi на маке через GitHub.
# Kimi пишет REMOTE_TASK.sh в этот репозиторий, Дмитрий выполняет одну строку:
#   cd ~/Documents/ChatGPT/Трейдинг/bybit-bot && git pull && bash REMOTE_RUN.sh
# Результат попадает в REMOTE_OUT.txt и пушится обратно, Kimi читает его через GitHub API.
cd "$(dirname "$0")"
OUT="REMOTE_OUT.txt"
{
  echo "=== REMOTE RUN $(date '+%Y-%m-%d %H:%M:%S %Z') | host: $(hostname) ==="
  echo "--- git ---"
  git log --oneline -3
  git status --short
  echo "--- TASK OUTPUT ---"
  bash REMOTE_TASK.sh 2>&1
  echo "=== END ==="
} > "$OUT" 2>&1
git add "$OUT" 2>/dev/null
git commit -q -m "remote run $(date '+%m-%d %H:%M')" 2>/dev/null || true
git push -q 2>&1
echo "Готово. Результат записан в REMOTE_OUT.txt и отправлен на GitHub."
