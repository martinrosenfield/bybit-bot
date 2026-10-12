#!/usr/bin/env python3
"""
Bybit demo trading bot — BTCUSDT / ETHUSDT, linear perpetuals, M15.

Strategy: EMA20/EMA50 cross on CLOSED candles + ATR14 for stops.
Risk: 0.25% of equity per trade, daily loss limit 1%, max 3 entries/day,
leverage cap x3, one position per symbol.

SAFETY: this bot ONLY connects to the Bybit DEMO environment (demo=True).
It can never hit the live API even if live keys are supplied.

Keys come from env: BYBIT_API_KEY, BYBIT_API_SECRET.
Config: config.json next to this script.

If dry_run=false in config, real demo orders are placed only when env
CONFIRM_LIVE=YES is set — an explicit human gate.
"""

import json
import os
import sys
import time
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from pybit.unified_trading import HTTP

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bybit_bot")


# ---------------------------------------------------------------- config

def load_config() -> dict:
    with open(BASE_DIR / "config.json", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()

DRY_RUN = bool(CFG["dry_run"])
CONFIRMED = os.environ.get("CONFIRM_LIVE", "") == "YES"
SYMBOLS = CFG["symbols"]
TIMEFRAME = str(CFG["timeframe"])          # "15"
EMA_FAST = int(CFG["ema_fast"])            # 20
EMA_SLOW = int(CFG["ema_slow"])            # 50
ATR_PERIOD = int(CFG["atr_period"])        # 14
RISK_PER_TRADE = float(CFG["risk_per_trade"])            # 0.0025
DAILY_LOSS_LIMIT = float(CFG["daily_loss_limit"])        # 0.01
MAX_ORDERS_PER_DAY = int(CFG["max_orders_per_day"])      # 3
LEVERAGE = int(CFG["leverage"])                          # 3
ATR_STOP_MULT = float(CFG["atr_stop_mult"])              # 1.5
ATR_TP_MULT = float(CFG["atr_tp_mult"])                  # 2.25 (RR ~1.5)
MAX_NOTIONAL_PCT = float(CFG["max_notional_pct_equity"]) # 0.5
POLL_SECONDS = int(CFG.get("poll_seconds", 20))
KLINES_NEEDED = EMA_SLOW + ATR_PERIOD + 10

if not DRY_RUN and not CONFIRMED:
    log.error("dry_run=false but CONFIRM_LIVE=YES not set. Refusing to start.")
    sys.exit(1)

# ---------------------------------------------------------------- session

session = HTTP(
    demo=True,  # HARD safety: demo environment only, always
    api_key=os.environ["BYBIT_API_KEY"],
    api_secret=os.environ["BYBIT_API_SECRET"],
    recv_window=30000,
    log_level="WARNING",
)


def checked(resp: dict, ctx: str) -> dict:
    if resp.get("retCode") != 0:
        raise RuntimeError(f"{ctx}: [{resp.get('retCode')}] {resp.get('retMsg')}")
    return resp


def jlog(event: str, **data):
    """Append a structured JSON line to today's event log."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **data}
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(LOG_DIR / f"events_{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- helpers

def get_equity() -> float:
    r = checked(session.get_wallet_balance(accountType="UNIFIED"), "wallet balance")
    return float(r["result"]["list"][0]["totalEquity"])


def get_klines(symbol: str) -> list[dict]:
    r = checked(
        session.get_kline(category="linear", symbol=symbol, interval=TIMEFRAME, limit=KLINES_NEEDED),
        f"kline {symbol}",
    )
    # v5 kline: [start, o, h, l, c, vol, turnover]
    rows = []
    for k in r["result"]["list"]:
        rows.append({
            "start": int(k[0]),
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
        })
    rows.sort(key=lambda x: x["start"])
    return rows


def ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(rows: list[dict], period: int) -> float:
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return sum(trs) / len(trs)
    # simple average of last `period` TRs — adequate for M15 stops
    return sum(trs[-period:]) / period


def detect_signal(rows: list[dict]) -> str | None:
    """Return 'Buy'/'Sell' on fresh EMA cross of the LAST CLOSED candle, else None."""
    closes = [r["close"] for r in rows]
    ef, es = ema(closes, EMA_FAST), ema(closes, EMA_SLOW)
    # last element = last closed candle (request is aligned to closed candles by start-time tracking below)
    i = len(closes) - 1
    if i < EMA_SLOW:
        return None
    prev_up = ef[i - 1] > es[i - 1]
    now_up = ef[i] > es[i]
    if now_up and not prev_up:
        return "Buy"
    if not now_up and prev_up:
        return "Sell"
    return None


def round_qty(qty: float, step: str) -> Decimal:
    return Decimal(str(qty)).quantize(Decimal(step), rounding=ROUND_DOWN)


def instrument_filters(symbol: str) -> dict:
    r = checked(session.get_instruments_info(category="linear", symbol=symbol), f"instrument {symbol}")
    f = r["result"]["list"][0]["lotSizeFilter"]
    return {"qty_step": f["qtyStep"], "min_qty": Decimal(f["minOrderQty"]),
            "max_qty": Decimal(f["maxOrderQty"])}


def calc_qty(symbol: str, equity: float, price: float, atr_val: float) -> Decimal | None:
    stop_dist = atr_val * ATR_STOP_MULT
    risk_amount = equity * RISK_PER_TRADE
    qty = risk_amount / stop_dist                      # size from risk
    notional_cap = equity * MAX_NOTIONAL_PCT
    if qty * price > notional_cap:                     # leverage/notional cap
        qty = notional_cap / price
    flt = instrument_filters(symbol)
    q = round_qty(qty, flt["qty_step"])
    if q < flt["min_qty"]:
        log.warning(f"{symbol}: qty {q} below min {flt['min_qty']} — skip")
        return None
    if q > flt["max_qty"]:
        q = flt["max_qty"]
    if float(q) * price < 5.0:                         # min notional 5 USDT
        log.warning(f"{symbol}: notional below $5 — skip")
        return None
    return q


def set_leverage(symbol: str):
    try:
        checked(session.set_leverage(
            category="linear", symbol=symbol,
            buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE)), f"leverage {symbol}")
        log.info(f"{symbol}: leverage set to x{LEVERAGE}")
    except RuntimeError as e:
        if "110043" in str(e) or "not modified" in str(e).lower():
            log.info(f"{symbol}: leverage already x{LEVERAGE}")
        else:
            raise


def open_position(symbol: str) -> dict | None:
    r = checked(session.get_positions(category="linear", symbol=symbol), f"positions {symbol}")
    for p in r["result"]["list"]:
        if float(p["size"]) > 0:
            return p
    return None


def daily_realized_pnl() -> float:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0.0
    cursor = None
    for _ in range(10):
        params = dict(category="linear", limit=100)
        if cursor:
            params["cursor"] = cursor
        r = checked(session.get_closed_pnl(**params), "closed pnl")
        for p in r["result"]["list"]:
            if p["updatedTime"][:10] > today:
                continue
            if p["updatedTime"][:10] < today:
                return total
            total += float(p["closedPnl"])
        cursor = r["result"].get("nextPageCursor")
        if not cursor:
            break
    return total


def entries_today(symbol: str | None = None) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = 0
    for f in LOG_DIR.glob(f"events_{day}.jsonl"):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") == "ENTRY" and (symbol is None or rec.get("symbol") == symbol):
                    n += 1
    return n


# ---------------------------------------------------------------- trading

def place_entry(symbol: str, side: str, qty: Decimal, price: float, atr_val: float):
    stop_dist = atr_val * ATR_STOP_MULT
    tp_dist = atr_val * ATR_TP_MULT
    if side == "Buy":
        sl = round(price - stop_dist, 1)
        tp = round(price + tp_dist, 1)
    else:
        sl = round(price + stop_dist, 1)
        tp = round(price - tp_dist, 1)

    if DRY_RUN:
        log.info(f"[DRY] {side} {qty} {symbol} @~{price} SL={sl} TP={tp}")
        jlog("ENTRY", symbol=symbol, side=side, qty=str(qty), price=price,
             sl=sl, tp=tp, dry_run=True)
        return

    r = checked(session.place_order(
        category="linear", symbol=symbol, side=side,
        orderType="Market", qty=str(qty),
        stopLoss=str(sl), takeProfit=str(tp),
        slTriggerBy="LastPrice", tpTriggerBy="LastPrice",
        positionIdx=0, timeInForce="IOC",
    ), f"place order {symbol}")
    log.info(f"LIVE-DEMO {side} {qty} {symbol} @~{price} SL={sl} TP={tp} id={r['result']['orderId']}")
    jlog("ENTRY", symbol=symbol, side=side, qty=str(qty), price=price,
         sl=sl, tp=tp, dry_run=False, order_id=r["result"]["orderId"])


# ---------------------------------------------------------------- main loop

def preflight():
    eq = get_equity()
    log.info(f"=== PREFLIGHT === env=demo dry_run={DRY_RUN} equity={eq:.2f} USDT-eq")
    jlog("PREFLIGHT", equity=eq, dry_run=DRY_RUN)
    for s in SYMBOLS:
        set_leverage(s)
        rows = get_klines(s)
        a = atr(rows, ATR_PERIOD)
        last = rows[-1]["close"]
        log.info(f"{s}: last={last} ATR={a:.2f} ({a / last * 100:.3f}%) "
                 f"stop={a * ATR_STOP_MULT:.2f} candles={len(rows)}")
    log.info("=================")


def main():
    preflight()
    state = {s: {"last_candle_start": None} for s in SYMBOLS}
    day_anchor = {"date": None, "equity": None}
    last_snapshot = 0.0

    while True:
        try:
            now = time.time()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if day_anchor["date"] != today:
                day_anchor = {"date": today, "equity": get_equity()}
                log.info(f"New day {today}, anchor equity={day_anchor['equity']:.2f}")

            if now - last_snapshot >= 3600:
                eq = get_equity()
                pnl = daily_realized_pnl()
                log.info(f"snapshot equity={eq:.2f} day_realized_pnl={pnl:.2f}")
                jlog("SNAPSHOT", equity=eq, day_realized_pnl=pnl)
                last_snapshot = now

            # daily loss guard (realized + open unrealized vs anchor)
            eq_now = get_equity()
            day_pnl_pct = (eq_now - day_anchor["equity"]) / day_anchor["equity"]
            if day_pnl_pct <= -DAILY_LOSS_LIMIT:
                if not state.get("daily_stop_logged"):
                    log.warning(f"DAILY LOSS LIMIT hit: {day_pnl_pct:.2%}. No new entries today.")
                    jlog("DAILY_STOP", pnl_pct=day_pnl_pct)
                    state["daily_stop_logged"] = True
                time.sleep(POLL_SECONDS)
                continue
            state["daily_stop_logged"] = False

            for s in SYMBOLS:
                if open_position(s):
                    continue
                if entries_today(s) >= MAX_ORDERS_PER_DAY:
                    continue

                rows = get_klines(s)
                cur_start = rows[-1]["start"]
                # act once per new closed candle
                if state[s]["last_candle_start"] is None:
                    state[s]["last_candle_start"] = cur_start
                    continue
                if cur_start == state[s]["last_candle_start"]:
                    continue
                state[s]["last_candle_start"] = cur_start

                # rows[-1] is the still-forming candle; the just-closed one is rows[-2]
                closed_rows = rows[:-1]
                sig = detect_signal(closed_rows)
                if not sig:
                    continue

                a = atr(closed_rows, ATR_PERIOD)
                price = closed_rows[-1]["close"]
                equity = get_equity()
                qty = calc_qty(s, equity, price, a)
                if qty is None:
                    continue

                log.info(f"SIGNAL {sig} {s} @~{price} ATR={a:.2f} qty={qty}")
                jlog("SIGNAL", symbol=s, side=sig, price=price, atr=a, qty=str(qty))
                place_entry(s, sig, qty, price, a)

            time.sleep(POLL_SECONDS)
        except Exception as e:
            log.exception(f"loop error: {e}")
            jlog("ERROR", error=str(e))
            time.sleep(60)


if __name__ == "__main__":
    main()
