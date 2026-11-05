"""約定を「1トレード（建てて→決済でゼロに戻るまで）」にまとめ、損益を計算する。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import replace
from typing import Optional

from .models import Execution, Trade

EPS = 1e-9


def classify_style(holding_days: int) -> str:
    if holding_days <= 0:
        return "デイトレ"
    if holding_days <= 30:
        return "スイング"
    return "中長期"


def _trade_id(key: tuple, first: Execution) -> str:
    raw = "|".join(str(k) for k in key) + f"|{first.trade_date}|{first.time}|{first.qty}|{first.price}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _build_trade(key: tuple, fills: list[Execution]) -> Trade:
    market, symbol, margin, account = key
    first, last = fills[0], fills[-1]
    direction = "long" if first.side == "buy" else "short"
    open_side = first.side

    def amt(e: Execution) -> float:
        return e.qty * e.price

    entry = [f for f in fills if f.side == open_side]
    exit_ = [f for f in fills if f.side != open_side]
    entry_qty = sum(f.qty for f in entry)
    exit_qty = sum(f.qty for f in exit_)
    avg_entry = sum(amt(f) for f in entry) / entry_qty
    avg_exit = sum(amt(f) for f in exit_) / exit_qty

    sign = 1 if direction == "long" else -1
    gross_local = sign * (sum(amt(f) for f in exit_) - sum(amt(f) for f in entry))
    fees_local = sum(f.fee for f in fills)
    pnl_local = gross_local - fees_local

    pnl_jpy: Optional[float] = None
    fees_jpy: Optional[float] = None
    entry_cost_jpy: Optional[float] = None
    if all(f.fx for f in fills):
        gross_jpy = sign * (sum(amt(f) * f.fx for f in exit_) - sum(amt(f) * f.fx for f in entry))
        fees_jpy = sum(f.fee * f.fx for f in fills)
        pnl_jpy = gross_jpy - fees_jpy
        entry_cost_jpy = sum(amt(f) * f.fx for f in entry)

    # 最大建玉
    pos = peak = 0.0
    for f in fills:
        pos += f.qty if f.side == open_side else -f.qty
        peak = max(peak, pos)

    holding = (last.trade_date - first.trade_date).days
    base = entry_cost_jpy if entry_cost_jpy else sum(amt(f) for f in entry)
    ret_basis = pnl_jpy if pnl_jpy is not None else pnl_local
    return_pct = round(ret_basis / base * 100, 2) if base else None
    result = "勝ち" if ret_basis > 0.5 else "負け" if ret_basis < -0.5 else "引き分け"

    return Trade(
        trade_id=_trade_id(key, first),
        market=market,
        symbol=symbol,
        name=next((f.name for f in fills if f.name), ""),
        direction=direction,
        margin=margin,
        account=account,
        broker=first.broker,
        entry_date=first.trade_date,
        exit_date=last.trade_date,
        holding_days=holding,
        style=classify_style(holding),
        qty=peak,
        avg_entry=round(avg_entry, 4),
        avg_exit=round(avg_exit, 4),
        currency=first.currency,
        pnl_local=round(pnl_local, 2),
        pnl_jpy=round(pnl_jpy) if pnl_jpy is not None else None,
        fees_jpy=round(fees_jpy) if fees_jpy is not None else None,
        entry_cost_jpy=round(entry_cost_jpy) if entry_cost_jpy is not None else None,
        return_pct=return_pct,
        result=result,
        fills=[
            {
                "date": f.trade_date.isoformat(),
                "time": f.time,
                "side": "買" if f.side == "buy" else "売",
                "qty": f.qty,
                "price": f.price,
                "fee": f.fee,
                "fx": f.fx,
                "source": f.source,
            }
            for f in fills
        ],
    )


def match(execs: list[Execution]) -> tuple[list[Trade], list[dict], list[str]]:
    """約定リストからトレードを組み立てる。

    戻り値: (決済済みトレード, 未決済ポジション, 警告)
    同じ銘柄でも 現物/信用・口座区分（特定/NISA等）が違えば別ポジションとして扱う。
    """
    # 重複行（同じCSVを2回渡した等）を除く
    seen = set()
    uniq = []
    # 時刻が無いCSV（同日の順序が不明）でも、同じ日の中では
    # 新規（現物買い・信用新規）→ 決済（現物売り・信用返済）の順に並べる
    def order(e: Execution):
        closing = e.is_close or (not e.margin and e.side == "sell")
        return (e.trade_date, e.time or "99:99", closing, e.source)

    for e in sorted(execs, key=order):
        k = (e.trade_date, e.time, e.market, e.symbol, e.side, e.qty, e.price, e.margin, e.account, e.broker)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    groups: dict[tuple, list[Execution]] = defaultdict(list)
    for e in uniq:
        groups[(e.market, e.symbol, e.margin, e.account)].append(e)

    trades: list[Trade] = []
    open_positions: list[dict] = []
    warnings: list[str] = []

    for key, items in groups.items():
        pos = 0.0  # +ロング / -ショート
        cycle: list[Execution] = []
        queue = list(items)
        while queue:
            e = queue.pop(0)
            delta = e.qty if e.side == "buy" else -e.qty
            if not cycle:
                # 現物の売り・信用の返済から始まる＝この期間より前に建てたもの
                if e.is_close or (e.side == "sell" and not e.margin):
                    warnings.append(
                        f"{e.source}: {e.symbol} の決済に対応する新規の約定がCSVにありません。"
                        "建てた時期を含むCSVを追加するか、手入力で補ってください"
                    )
                    continue
            new_pos = pos + delta
            if pos and new_pos and (pos > 0) != (new_pos > 0):
                # ドテン（1回の約定でロング→ショート等）: 約定を分割
                close_qty = abs(pos)
                cycle.append(replace(e, qty=close_qty, fee=e.fee * close_qty / e.qty))
                trades.append(_build_trade(key, cycle))
                rest = e.qty - close_qty
                queue.insert(0, replace(e, qty=rest, fee=e.fee * rest / e.qty))
                cycle, pos = [], 0.0
                continue
            cycle.append(e)
            pos = new_pos
            if abs(pos) < EPS:
                trades.append(_build_trade(key, cycle))
                cycle, pos = [], 0.0
        if cycle:
            market, symbol, margin, account = key
            open_positions.append(
                {
                    "market": market,
                    "symbol": symbol,
                    "name": next((f.name for f in cycle if f.name), ""),
                    "margin": margin,
                    "position": pos,
                    "since": cycle[0].trade_date.isoformat(),
                    "fills": len(cycle),
                }
            )

    trades.sort(key=lambda t: (t.exit_date, t.entry_date, t.symbol))
    return trades, open_positions, warnings


def group_daytrades(trades: list[Trade]) -> list[dict]:
    """デイトレを1日1件にまとめる（Notionに「デイトレ日次」として登録する用）。"""
    days: dict[tuple, list[Trade]] = defaultdict(list)
    for t in trades:
        if t.style == "デイトレ":
            days[(t.exit_date, t.market)].append(t)
    out = []
    for (d, market), ts in sorted(days.items()):
        pnl = [t.pnl_jpy for t in ts if t.pnl_jpy is not None]
        out.append(
            {
                "day_id": "day-" + hashlib.sha1(f"day|{d}|{market}".encode()).hexdigest()[:8],
                "date": d.isoformat(),
                "market": market,
                "trades": len(ts),
                "wins": sum(1 for t in ts if t.result == "勝ち"),
                "losses": sum(1 for t in ts if t.result == "負け"),
                "pnl_jpy": round(sum(pnl)) if pnl else None,
                "symbols": sorted({f"{t.symbol} {t.name}".strip() for t in ts}),
                "trade_ids": [t.trade_id for t in ts],
            }
        )
    return out
