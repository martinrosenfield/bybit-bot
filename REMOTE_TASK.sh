#!/bin/bash
# REMOTE_TASK.sh — чтение центрального контекста проектов для Kimi, 27.10.2026.
# ТОЛЬКО ЧТЕНИЕ разрешённых Markdown-файлов. Ничего не изменяет и не запускает.
python3 - <<'PY'
from pathlib import Path
from datetime import datetime

root = Path.home() / "Documents" / "ChatGPT"
files = [
    "ОБМЕН Claude-ChatGPT/AGENTS.md",
    "ОБМЕН Claude-ChatGPT/README.md",
    "ОБМЕН Claude-ChatGPT/ЗАДАЧИ.md",
    "ОБМЕН Claude-ChatGPT/ПАМЯТЬ-Claude.md",
    "ОБМЕН Claude-ChatGPT/проекты/ИД-ГНБ-и-Авито.md",
    "ОБМЕН Claude-ChatGPT/проекты/Сервис-возвратов.md",
    "ОБМЕН Claude-ChatGPT/проекты/Трейдинг.md",
    "ГНБ/tender-filter/ПРОЧИТАЙТЕ.md",
]

print(f"ROOT: {root}")
print(f"TIME: {datetime.now().astimezone().isoformat(timespec='seconds')}")
print("MODE: allowlisted Markdown context only")

for rel in files:
    path = root / rel
    print(f"\n===== FILE: {rel} =====")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        continue
    if len(text) > 60000:
        print(text[:60000])
        print(f"\n[TRUNCATED AT 60000 CHARS; TOTAL {len(text)}]")
    else:
        print(text)
    print(f"===== END FILE: {rel} =====")

journal = root / "ОБМЕН Claude-ChatGPT" / "ЖУРНАЛ.md"
print("\n===== FILE: ОБМЕН Claude-ChatGPT/ЖУРНАЛ.md (LAST 100 LINES) =====")
try:
    lines = journal.read_text(encoding="utf-8").splitlines()
    print("\n".join(lines[-100:]))
except Exception as exc:
    print(f"ERROR: {type(exc).__name__}: {exc}")
print("===== END JOURNAL =====")
print("DONE")
PY
