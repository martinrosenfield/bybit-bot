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

from __future__ import annotations

import json
import os
import sys
import time
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
import fcntl
import hashlib

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

INSTANCE_LOCK = open(BASE_DIR / "instance.lock", "a")
try:
    fcntl.flock(INSTANCE_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("Another managed instance is running")
STATE_PATH = BASE_DIR / "runtime_state.json"
RUNTIME = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"attempts": {}, "halted": [], "entries_paused": True}

for pending_symbol in RUNTIME.get("pending", {}):
    if pending_symbol not in RUNTIME["halted"]:
        RUNTIME["halted"].append(pending_symbol)

def save_state():
    temp = STATE_PATH.with_suffix(".tmp")
    with open(temp, "w") as fh:
        json.dump(RUNTIME, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, STATE_PATH)

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
ATR_TP_MULT = float(CFG["atr_tp_mult"])                  # 3.0 x ATR
MAX_NOTIONAL_PCT = float(CFG["max_notional_pct_equity"]) # 0.5
TAKER_FEE = float(CFG.get("taker_fee_rate", 0.00055))
POLL_SECONDS = int(CFG.get("poll_seconds", 20))
KLINES_NEEDED = EMA_SLOW + ATR_PERIOD + 10

if not DRY_RUN and (not CONFIRMED or RUNTIME.get("entries_paused", True)):
    log.error("Demo execution is paused or CONFIRM_LIVE=YES is absent. Refusing to start.")
    sys.exit(1)

# ---------------------------------------------------------------- session

session = HTTP(
    demo=True,  # HARD safety: demo environment only, always
    api_key=os.environ["BYBIT_API_KEY"],
    api_secret=os.environ["BYBIT_API_SECRET"],
    recv_window=30000,
    logging_level=logging.WARNING,
    timeout=10,
    max_retries=1,
)
if session.endpoint != "https://api-demo.bybit.com":
    raise SystemExit("Only the official demo endpoint is permitted")


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
    increment = Decimal(step)
    return (Decimal(str(qty)) / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def instrument_filters(symbol: str) -> dict:
    r = checked(session.get_instruments_info(category="linear", symbol=symbol), f"instrument {symbol}")
    f = r["result"]["list"][0]["lotSizeFilter"]
    return {"qty_step": f["qtyStep"], "min_qty": Decimal(f["minOrderQty"]),
            "max_qty": Decimal(f.get("maxMktOrderQty", f["maxOrderQty"])),
            "min_notional": Decimal(f.get("minNotionalValue", "5")),
            "tick_size": r["result"]["list"][0]["priceFilter"]["tickSize"]}


def calc_qty(symbol: str, equity: float, price: float, atr_val: float) -> Decimal | None:
    stop_dist = atr_val * ATR_STOP_MULT
    if stop_dist <= 0 or equity <= 0 or price <= 0:
        raise ValueError("Invalid sizing data")
    risk_amount = equity * RISK_PER_TRADE
    qty = risk_amount / (stop_dist + 2 * TAKER_FEE * price)
    notional_cap = equity * MAX_NOTIONAL_PCT
    if qty * price > notional_cap:                     # leverage/notional cap
        qty = notional_cap / price
    flt = instrument_filters(symbol)
    q = round_qty(qty, flt["qty_step"])
    if q < flt["min_qty"]:
        log.warning(f"{symbol}: qty {q} below min {flt['min_qty']} — skip")
        return None
    if q > flt["max_qty"]:
        q = round_qty(flt["max_qty"], flt["qty_step"])
    if q * Decimal(str(price)) < flt["min_notional"]:
        log.warning(f"{symbol}: notional below $5 — skip")
        return None
    return q


def set_leverage(symbol: str):
    try:
        checked(session.set_leverage(
            category="linear", symbol=symbol,
            buyLeverage=str(LEVERAGE), sellLeverage=str(LEVERAGE)), f"leverage {symbol}")
        log.info(f"{symbol}: leverage set to x{LEVERAGE}")
    except Exception as e:
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
    now = datetime.now(timezone.utc)
    start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    total = 0.0
    cursor = None
    seen_cursors = set()
    while True:
        params = dict(category="linear", limit=100, startTime=start, endTime=int(now.timestamp()*1000))
        if cursor:
            params["cursor"] = cursor
        r = checked(session.get_closed_pnl(**params), "closed pnl")
        for p in r["result"]["list"]:
            total += float(p["closedPnl"])
        cursor = r["result"].get("nextPageCursor")
        if not cursor:
            break
        if cursor in seen_cursors:
            raise RuntimeError("Repeated closed-PnL cursor")
        seen_cursors.add(cursor)
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

def place_entry(symbol: str, side: str, qty: Decimal, price: float, atr_val: float, link_id: str):
    stop_dist = atr_val * ATR_STOP_MULT
    tp_dist = atr_val * ATR_TP_MULT
    if side == "Buy":
        sl = price - stop_dist
        tp = price + tp_dist
    else:
        sl = price + stop_dist
        tp = price - tp_dist
    tick = instrument_filters(symbol)["tick_size"]
    sl, tp = str(round_qty(sl, tick)), str(round_qty(tp, tick))
    # Tick rounding must not increase the planned loss beyond the budget.
    equity = get_equity()
    loss_per_unit = abs(price - float(sl)) + TAKER_FEE * (price + float(sl))
    filters = instrument_filters(symbol)
    qty = round_qty(min(qty, Decimal(str(equity * RISK_PER_TRADE / loss_per_unit)),
                        Decimal(str(equity * MAX_NOTIONAL_PCT / price)), filters["max_qty"]),
                    filters["qty_step"])
    if qty < filters["min_qty"] or qty * Decimal(str(price)) < filters["min_notional"]:
        jlog("SKIP", symbol=symbol, reason="Risk budget below minimum including fee allowance")
        return

    if DRY_RUN:
        log.info(f"[DRY] {side} {qty} {symbol} @~{price} SL={sl} TP={tp}")
        jlog("DRY_RUN", symbol=symbol, side=side, qty=str(qty), price=price,
             sl=sl, tp=tp, dry_run=True, planned_risk=float(qty)*loss_per_unit)
        return

    if RUNTIME.get("entries_paused", True) or symbol in RUNTIME["halted"]:
        raise RuntimeError("New entries require explicit user confirmation here")
    # Also re-read config at the transmission boundary, so a pause takes effect without restart.
    if load_config().get("dry_run") is not False:
        raise RuntimeError("Order transmission blocked by current dry_run config")
    key = f"{datetime.now(timezone.utc):%Y-%m-%d}:{symbol}:{link_id}"
    if link_id in RUNTIME["attempts"].values():
        raise RuntimeError("Order attempt already reserved; reconcile before retry")
    RUNTIME["attempts"][key] = link_id
    RUNTIME.setdefault("pending", {})[symbol] = link_id
    save_state()
    planned_risk = float(qty) * loss_per_unit
    log.info("%s planned_risk=%.8f equity=%.8f", symbol, planned_risk, equity)
    try:
        r = checked(session.place_order(
            category="linear", symbol=symbol, side=side, orderType="Market", qty=str(qty),
            stopLoss=sl, takeProfit=tp, slTriggerBy="LastPrice", tpTriggerBy="LastPrice",
            positionIdx=0, timeInForce="IOC", orderLinkId=link_id, tpslMode="Full",
        ), "place order")
        order_id = r["result"]["orderId"]
        jlog("ORDER_ACCEPTED", symbol=symbol, order_id=order_id,
             order_link_id=link_id, dry_run=False, planned_risk=planned_risk)
        for _ in range(10):
            time.sleep(1)
            position = open_position(symbol)
            executions = checked(session.get_executions(category="linear", symbol=symbol,
                                 orderId=order_id, limit=100), "execution verification")["result"]
            fills = [e for e in executions["list"] if e.get("orderId") == order_id
                     and e.get("symbol") == symbol and e.get("side") == side
                     and e.get("execType") == "Trade"]
            filled = sum((Decimal(e["execQty"]) for e in fills), Decimal("0"))
            if (not executions.get("nextPageCursor") and filled == qty and position
                    and position["side"] == side and Decimal(position["size"]) == qty
                    and int(position.get("positionIdx", -1)) == 0
                    and Decimal(position.get("stopLoss") or "0") == Decimal(sl)
                    and Decimal(position.get("takeProfit") or "0") == Decimal(tp)):
                actual_price = sum(Decimal(e["execPrice"]) * Decimal(e["execQty"])
                                   for e in fills) / filled
                jlog("ENTRY", symbol=symbol, side=side, qty=str(filled), price=str(actual_price),
                     sl=position["stopLoss"], tp=position["takeProfit"], dry_run=False,
                     order_id=order_id, order_link_id=link_id, planned_risk=planned_risk,
                     execution_ids=[e["execId"] for e in fills], verification="execution_and_server_sltp")
                del RUNTIME["pending"][symbol]
                save_state()
                log.info("DEMO EXECUTION VERIFIED %s with server SL/TP", symbol)
                return
        raise RuntimeError("Execution or server SL/TP not confirmed")
    except Exception:
        if symbol not in RUNTIME["halted"]:
            RUNTIME["halted"].append(symbol)
        save_state()
        jlog("ACTION_REQUIRED", symbol=symbol, order_link_id=link_id,
             reason="Unconfirmed order/execution/protection; further entries halted")
        raise RuntimeError("Demo execution/protection requires review") from None


# ---------------------------------------------------------------- main loop

def preflight():
    eq = get_equity()
    log.info(f"=== PREFLIGHT === env=demo dry_run={DRY_RUN} equity={eq:.2f} USDT-eq")
    jlog("PREFLIGHT", equity=eq, dry_run=DRY_RUN)
    for s in SYMBOLS:
        if not DRY_RUN:
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
    day_anchor = RUNTIME.get("day_anchor", {"date": None, "equity": None})
    last_snapshot = 0.0

    while True:
        try:
            now = time.time()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if day_anchor["date"] != today:
                day_anchor = {"date": today, "equity": get_equity()}
                RUNTIME["day_anchor"] = day_anchor
                save_state()
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
            if day_pnl_pct <= -DAILY_LOSS_LIMIT or RUNTIME.get("halt_day") == today:
                RUNTIME["halt_day"] = today
                save_state()
                if not state.get("daily_stop_logged"):
                    log.warning(f"DAILY LOSS LIMIT hit: {day_pnl_pct:.2%}. No new entries today.")
                    jlog("DAILY_STOP", pnl_pct=day_pnl_pct)
                    state["daily_stop_logged"] = True
                time.sleep(POLL_SECONDS)
                continue
            state["daily_stop_logged"] = False

            for s in SYMBOLS:
                if s in RUNTIME["halted"] or s in RUNTIME.get("pending", {}):
                    continue
                if open_position(s):
                    continue
                pending = checked(session.get_open_orders(category="linear", symbol=s, openOnly=0), "open orders")
                if pending["result"]["list"]:
                    continue
                if entries_today(s) >= MAX_ORDERS_PER_DAY:
                    continue

                rows = get_klines(s)
                server_ms = int(checked(session.get_server_time(), "server time")["time"])
                closed_rows = [row for row in rows if row["start"] + int(TIMEFRAME)*60000 <= server_ms]
                if len(closed_rows) < EMA_SLOW + 2:
                    continue
                cur_start = closed_rows[-1]["start"]
                if server_ms - cur_start > 2*int(TIMEFRAME)*60000:
                    continue
                # act once per new closed candle
                if state[s]["last_candle_start"] is None:
                    state[s]["last_candle_start"] = cur_start
                    continue
                if cur_start == state[s]["last_candle_start"]:
                    continue
                state[s]["last_candle_start"] = cur_start

                # rows[-1] is the still-forming candle; the just-closed one is rows[-2]
                sig = detect_signal(closed_rows)
                if not sig:
                    continue

                a = atr(closed_rows, ATR_PERIOD)
                ticker = checked(session.get_tickers(category="linear", symbol=s), "ticker")["result"]["list"][0]
                price = float(ticker["ask1Price"] if sig == "Buy" else ticker["bid1Price"])
                equity = get_equity()
                qty = calc_qty(s, equity, price, a)
                if qty is None:
                    continue

                log.info(f"SIGNAL {sig} {s} @~{price} ATR={a:.2f} qty={qty}")
                jlog("SIGNAL", symbol=s, side=sig, price=price, atr=a, qty=str(qty))
                key = f"{today}:{s}:{cur_start}:{sig}"
                attempts = RUNTIME["attempts"]
                if key in attempts or sum(k.startswith(today+":"+s+":") for k in attempts) >= MAX_ORDERS_PER_DAY:
                    continue
                link_id = "demo-" + hashlib.sha256(key.encode()).hexdigest()[:30]
                # Persist before network transmission; ambiguity never triggers a new ID/retry.
                place_entry(s, sig, qty, price, a, link_id)

            time.sleep(POLL_SECONDS)
        except Exception as e:
            log.error("loop error type=%s (request details suppressed)", type(e).__name__)
            jlog("ERROR", error_type=type(e).__name__)
            time.sleep(60)


if __name__ == "__main__":
    main()
