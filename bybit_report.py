#!/usr/bin/env python3
"""
Daily report for the Bybit demo bot.

Usage:
  python3 bybit_report.py           # report for today
  python3 bybit_report.py 2026-10-13  # report for a specific day (UTC)

Reads local JSONL event logs (logs/events_YYYY-MM-DD.jsonl) and queries the
Bybit demo API for closed PnL and current state. Read-only, safe to run
while the bot is working.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pybit.unified_trading import HTTP

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"


def day_str() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_events(day: str) -> list[dict]:
    path = LOG_DIR / f"events_{day}.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main():
    day = day_str()
    events = read_events(day)

    session = HTTP(
        demo=True,
        api_key=os.environ["BYBIT_API_KEY"],
        api_secret=os.environ["BYBIT_API_SECRET"],
        recv_window=30000,
        logging_level=logging.WARNING,
    )

    bal = session.get_wallet_balance(accountType="UNIFIED")
    equity = float(bal["result"]["list"][0]["totalEquity"])

    positions = session.get_positions(category="linear", settleCoin="USDT")
    open_pos = [p for p in positions["result"]["list"] if float(p["size"]) > 0]

    pnl_today = 0.0
    cursor = None
    while True:
        params = dict(category="linear", limit=100)
        if cursor:
            params["cursor"] = cursor
        r = session.get_closed_pnl(**params)
        for p in r["result"]["list"]:
            if p["updatedTime"][:10] == day:
                pnl_today += float(p["closedPnl"])
        cursor = r["result"].get("nextPageCursor")
        if not cursor:
            break

    entries = [e for e in events if e.get("event") == "ENTRY"]
    signals = [e for e in events if e.get("event") == "SIGNAL"]
    errors = [e for e in events if e.get("event") == "ERROR"]
    stops = [e for e in events if e.get("event") == "DAILY_STOP"]
    snapshots = [e for e in events if e.get("event") == "SNAPSHOT"]

    anchor = None
    for e in events:
        if e.get("event") == "PREFLIGHT":
            anchor = e.get("equity")
    if snapshots:
        anchor = snapshots[0].get("equity", anchor)

    print(f"===== Bybit demo report, {day} (UTC) =====")
    print(f"Equity now:        {equity:,.2f} USDT-eq")
    if anchor:
        print(f"Anchor equity:     {anchor:,.2f}  ({(equity - anchor) / anchor * 100:+.2f}%)")
    print(f"Closed PnL (API):  {pnl_today:+.2f} USDT")
    print(f"Signals / entries: {len(signals)} / {len(entries)}")
    for e in entries:
        tag = "DRY" if e.get("dry_run") else "LIVE"
        print(f"  [{tag}] {e['side']} {e['qty']} {e['symbol']} @~{e['price']} SL={e['sl']} TP={e['tp']}")
    print(f"Open positions:    {len(open_pos)}")
    for p in open_pos:
        upnl = float(p.get("unrealisedPnl", 0))
        print(f"  {p['side']} {p['size']} {p['symbol']} entry={p['avgPrice']} uPnL={upnl:+.2f}")
    print(f"Daily stops:       {len(stops)}   Errors: {len(errors)}")
    for e in errors[-5:]:
        print(f"  ! {e['ts']} {e.get('error', '')[:120]}")


if __name__ == "__main__":
    main()
