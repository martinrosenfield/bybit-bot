#!/bin/bash
# REMOTE_TASK.sh — карта папки ChatGPT для Kimi, 27.10.2026.
# ТОЛЬКО ЧТЕНИЕ: имена, размеры и даты файлов. Содержимое файлов НЕ читается.
python3 - <<'PY'
from pathlib import Path
from datetime import datetime
import os

root = Path.home() / "Documents" / "ChatGPT"
print(f"ROOT: {root}")
print("MODE: inventory only; no file contents")
print(f"TIME: {datetime.now().astimezone().isoformat(timespec='seconds')}")

if not root.is_dir():
    print("ERROR: folder not found or not a directory")
    raise SystemExit(1)

skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__"}
max_depth = 5
max_entries = 3000
count = 0
stopped = False

for current, dirs, files in os.walk(root, followlinks=False):
    current_path = Path(current)
    rel_current = current_path.relative_to(root)
    depth = 0 if str(rel_current) == "." else len(rel_current.parts)
    dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
    files = sorted(files)

    if depth >= max_depth:
        dirs[:] = []

    for directory in dirs:
        rel = (current_path / directory).relative_to(root)
        print(f"[DIR]  {rel}/")
        count += 1
        if count >= max_entries:
            stopped = True
            break
    if stopped:
        break

    for filename in files:
        path = current_path / filename
        rel = path.relative_to(root)
        try:
            stat = path.lstat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            kind = "LINK" if path.is_symlink() else "FILE"
            print(f"[{kind}] {rel}\t{size} bytes\t{modified}")
        except OSError as exc:
            print(f"[ERR]  {rel}\t{type(exc).__name__}")
        count += 1
        if count >= max_entries:
            stopped = True
            break
    if stopped:
        break

print(f"ENTRIES_SHOWN: {count}")
if stopped:
    print(f"TRUNCATED: limit {max_entries} entries; deepen selected folders in the next read-only task")
print("DONE")
PY
