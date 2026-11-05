"""約定を「1トレード（建てて→決済でゼロに戻るまで）」にまとめ、損益を計算する。"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
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
    # 時刻・手数料は含めない（返済行から復元した新規と、後から取り込んだ実際の新規で同じIDになるように）
    raw = "|".join(str(k) for k in key) + f"|{first.trade_date}|{first.qty}|{first.price}"
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

    closes = [f for f in exit_]
    broker_pnl = (
        round(sum(f.broker_pnl for f in closes)) if closes and all(f.broker_pnl is not None for f in closes) else None
    )
    return Trade(
        broker_pnl=broker_pnl,
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


def match(execs: list[Execution], splits: list[tuple] | None = None) -> tuple[list[Trade], list[dict], list[str]]:
    """約定リストからトレードを組み立てる。

    戻り値: (決済済みトレード, 未決済ポジション, 警告)
    同じ銘柄でも 現物/信用・口座区分（特定/NISA等）が違えば別ポジションとして扱う。

    - 信用: 建ててから返済で建玉がゼロに戻るまでを1トレードとする。
    - 現物: 売るたびに1トレードとし、取得単価は保有株の移動平均（手数料込み）で計算する
      （証券会社の実現損益・特定口座の計算と同じ方式）。
    splits: 株式分割 [(銘柄コード, 分割日, 倍率), ...]。分割日以降、保有数量を倍率倍にする（取得総額は変えない）。
    """
    # 時刻が無いCSV（同日の順序が不明）でも、同じ日の中では
    # 新規（現物買い・信用新規）→ 決済（現物売り・信用返済）の順に並べる
    def order(e: Execution):
        closing = e.is_close or (not e.margin and e.side == "sell")
        return (e.trade_date, e.time or "99:99", closing, e.source)

    # 重複行（同じ期間のCSVを2回渡した等）を除く。
    # 1つのファイル内で同じ内容の行が複数あるのは別々の約定なので残し、
    # ファイルをまたいだ重複だけを除く（同じ内容の行は、最も多く含むファイルの件数まで残す）。
    def sig(e: Execution):
        return (e.trade_date, e.time, e.market, e.symbol, e.side, e.qty, e.price, round(e.fee, 4),
                e.margin, e.account, e.broker, e.open_ref)

    # 同じファイル（同じファイル名・行番号）を2回渡した場合は、まずそれを除く
    seen_src = set()
    deduped = []
    for e in execs:
        if e.source in seen_src:
            continue
        seen_src.add(e.source)
        deduped.append(e)
    execs = deduped

    per_file: dict[str, Counter] = defaultdict(Counter)
    for e in execs:
        per_file[e.source.rsplit(":", 1)[0]][sig(e)] += 1
    allowed: Counter = Counter()
    for c in per_file.values():
        for k, n in c.items():
            allowed[k] = max(allowed[k], n)
    used: Counter = Counter()
    uniq = []
    for e in sorted(execs, key=order):
        k = sig(e)
        if used[k] >= allowed[k]:
            continue
        used[k] += 1
        uniq.append(e)

    # 返済の行に建玉の情報がある場合は、新規の約定を復元する（建てた日がCSVの期間外でも損益を出せる）。
    # 同じ新規の約定がCSVにもある場合はそちらを使い、復元した分は捨てる。
    real_open = defaultdict(float)
    for e in uniq:
        if e.margin and not e.is_close:
            real_open[(e.market, e.symbol, e.account, e.side, e.trade_date, round(e.price, 4))] += e.qty
    restored = []
    for e in uniq:
        if not (e.is_close and e.open_ref):
            continue
        od, op, ofee = e.open_ref
        open_side = "buy" if e.side == "sell" else "sell"
        rk = (e.market, e.symbol, e.account, open_side, od, round(op, 4))
        if real_open[rk] >= e.qty - EPS:
            real_open[rk] -= e.qty
            continue
        restored.append(
            replace(e, trade_date=od, time="", side=open_side, price=op, fee=ofee, is_close=False,
                    open_ref=None, broker_pnl=None, synthetic=True, source=e.source + "（建玉）")
        )
    uniq = sorted(uniq + restored, key=order)

    groups: dict[tuple, list[Execution]] = defaultdict(list)
    for e in uniq:
        groups[(e.market, e.symbol, e.margin, e.account)].append(e)

    trades: list[Trade] = []
    open_positions: list[dict] = []
    warnings: list[str] = []

    for key, items in groups.items():
        if not key[2]:  # 現物
            t2, op, w = _match_cash(key, items, splits or [])
            trades += t2
            open_positions += op
            warnings += w
            continue
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


def _match_cash(key: tuple, items: list[Execution], splits: list[tuple]):
    """現物: 移動平均法。売るたびに1トレード。"""
    market, symbol, margin, account = key
    trades, warnings = [], []
    my_splits = sorted((d, r) for (sym, d, r) in splits if sym == symbol)
    qty = 0.0
    gross_local = fee_local = 0.0
    gross_jpy: Optional[float] = 0.0
    fee_jpy: Optional[float] = 0.0
    held: list[Execution] = []  # 現在の保有を作った買い
    sells_in_holding = 0

    def reset():
        nonlocal qty, gross_local, fee_local, gross_jpy, fee_jpy, held, sells_in_holding
        qty, gross_local, fee_local, gross_jpy, fee_jpy, held, sells_in_holding = 0.0, 0.0, 0.0, 0.0, 0.0, [], 0

    for e in items:
        while my_splits and my_splits[0][0] <= e.trade_date:
            _, ratio = my_splits.pop(0)
            qty *= ratio
        if e.side == "buy":
            qty += e.qty
            gross_local += e.qty * e.price
            fee_local += e.fee
            if gross_jpy is not None and e.fx:
                gross_jpy += e.qty * e.price * e.fx
                fee_jpy += e.fee * e.fx
            else:
                gross_jpy = fee_jpy = None
            held.append(e)
            continue
        # 売り
        if qty < EPS:
            warnings.append(
                f"{e.source}: {symbol} の売りに対応する買いがCSVにありません。"
                "買った時期を含むCSVを追加するか、手入力で補ってください"
            )
            continue
        sq = e.qty
        if sq > qty + EPS:
            warnings.append(
                f"{e.source}: {symbol} を保有数（{qty:g}株）より多く売っています（{sq:g}株）。"
                "CSVの期間より前に買った分があるか、株式分割の可能性があります。保有数分だけ計算しました"
            )
            sq = qty
        r = sq / qty
        sell_fee = e.fee * sq / e.qty
        cost_gross_local, cost_fee_local = gross_local * r, fee_local * r
        pnl_local = sq * e.price - sell_fee - cost_gross_local - cost_fee_local
        pnl_jpy = fees_j = entry_j = None
        if gross_jpy is not None and e.fx:
            cg, cf = gross_jpy * r, fee_jpy * r
            pnl_jpy = sq * e.price * e.fx - sell_fee * e.fx - cg - cf
            fees_j = sell_fee * e.fx + cf
            entry_j = cg
        full_exit = abs(sq - qty) < EPS
        first = held[0]
        if full_exit and sells_in_holding == 0:
            tid = _trade_id(key, first)  # 1回の売りで全部手放したとき（従来どおりのID）
        else:
            raw = "|".join(str(k) for k in key) + f"|sell|{e.trade_date}|{sq}|{e.price}"
            tid = hashlib.sha1(raw.encode()).hexdigest()[:12]
        holding = (e.trade_date - first.trade_date).days
        ret_basis = pnl_jpy if pnl_jpy is not None else pnl_local
        base = entry_j if entry_j else cost_gross_local
        fills = held + [replace(e, qty=sq, fee=sell_fee)]
        trades.append(
            Trade(
                trade_id=tid,
                market=market,
                symbol=symbol,
                name=next((f.name for f in fills if f.name), ""),
                direction="long",
                margin=False,
                account=account,
                broker=e.broker,
                entry_date=first.trade_date,
                exit_date=e.trade_date,
                holding_days=holding,
                style=classify_style(holding),
                qty=sq,
                avg_entry=round(gross_local / qty, 4),
                avg_exit=round(e.price, 4),
                currency=e.currency,
                pnl_local=round(pnl_local, 2),
                pnl_jpy=round(pnl_jpy) if pnl_jpy is not None else None,
                fees_jpy=round(fees_j) if fees_j is not None else None,
                entry_cost_jpy=round(entry_j) if entry_j is not None else None,
                return_pct=round(ret_basis / base * 100, 2) if base else None,
                result="勝ち" if ret_basis > 0.5 else "負け" if ret_basis < -0.5 else "引き分け",
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
        )
        qty -= sq
        gross_local -= cost_gross_local
        fee_local -= cost_fee_local
        if gross_jpy is not None:
            gross_jpy *= 1 - r
            fee_jpy *= 1 - r
        sells_in_holding += 1
        if qty < EPS:
            reset()

    open_positions = []
    if qty > EPS:
        open_positions.append(
            {
                "market": market,
                "symbol": symbol,
                "name": next((f.name for f in held if f.name), ""),
                "margin": False,
                "position": qty,
                "since": held[0].trade_date.isoformat() if held else "",
                "fills": len(held),
            }
        )
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
