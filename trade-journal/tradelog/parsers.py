"""証券会社CSV（SBI証券・楽天証券／日本株・米国株）と手入力CSVの読み込み。

各社のCSVは列名や前置きの行が異なるため、固定フォーマットではなく
「列名の候補（エイリアス）」で列を特定する方式にしている。
列名が想定と違った場合は ALIASES に候補を追加すれば対応できる。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path
from typing import Optional

from .models import Execution


# 列の役割 -> 列名の候補（先に書いたものほど優先）
ALIASES: dict[str, list[str]] = {
    "date": ["約定日", "国内約定日", "約定日時", "約定日付", "取引日", "日付"],
    "time": ["約定時刻", "時刻", "約定時間"],
    "symbol": ["銘柄コード", "ティッカー", "ティッカーコード", "コード", "シンボル"],
    "name": ["銘柄名", "銘柄"],
    "side": ["売買区分", "売買", "取引", "取引種別"],
    "trade_type": ["取引区分", "信用区分"],
    "qty": ["数量［株］", "数量[株]", "約定数量", "数量", "株数", "約定株数"],
    "price": ["単価［円］", "単価［USドル］", "単価[円]", "単価[USドル]", "約定単価", "単価", "約定価格"],
    "fee": ["手数料［円］", "手数料［USドル］", "手数料[円]", "手数料[USドル]", "手数料/諸経費等", "手数料", "手数料等"],
    "fee_tax": ["税金等［円］", "税金［USドル］", "税金等[円]", "税金[USドル]", "税額", "消費税"],
    "other_cost": ["諸費用［円］", "諸費用[円]", "諸費用"],
    "fx": ["為替レート", "約定為替レート", "適用為替レート", "為替"],
    "currency": ["決済通貨", "通貨"],
    "account": ["口座区分", "口座", "預り", "預り区分"],
    "amount_jpy": ["受渡金額［円］", "受渡金額[円]"],
    "amount_usd": ["受渡金額［USドル］", "受渡金額[USドル]"],
    "market": ["マーケット"],  # 手入力テンプレート用（JP/US）
    "memo": ["メモ", "備考"],
}

REQUIRED = ["date", "symbol", "side", "qty", "price"]


class ParseError(Exception):
    pass


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932", "shift_jis", "euc_jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError(f"{path.name}: 文字コードを判定できませんでした")


def _norm(s: str) -> str:
    return (s or "").strip().replace(" ", "").replace("　", "")


def _find_columns(header: list[str]) -> dict[str, int]:
    cols = [_norm(h) for h in header]
    found: dict[str, int] = {}
    for role, names in ALIASES.items():
        for name in names:
            n = _norm(name)
            if n in cols:
                found[role] = cols.index(n)
                break
    return found


def _locate_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """前置きの行を飛ばして、必須列がそろう行を見出し行とする。"""
    for i, row in enumerate(rows[:60]):
        cols = _find_columns(row)
        if all(r in cols for r in REQUIRED):
            return i, cols
    raise ParseError("見出し行（約定日・銘柄コード・売買・数量・単価）が見つかりませんでした")


def detect_broker(text: str, filename: str) -> str:
    head = text[:3000]
    if "［株］" in head or "［円］" in head or "［USドル］" in head or "rakuten" in filename.lower():
        return "楽天証券"
    if "手数料/諸経費等" in head or "SBI" in head or "sbi" in filename.lower():
        return "SBI証券"
    if "マーケット" in head:
        return "手入力"
    return "不明"


_NUM_RE = re.compile(r"[^0-9.\-]")


def to_number(s: str) -> float:
    s = (s or "").strip()
    if s in ("", "-", "--", "---", "－"):
        return 0.0
    s = s.replace("，", ",").replace("−", "-").replace("▲", "-").replace("△", "-")
    s = _NUM_RE.sub("", s)
    if s in ("", "-", "."):
        return 0.0
    return float(s)


_DATE_RE = re.compile(r"(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def parse_date(s: str) -> date:
    m = _DATE_RE.search(s or "")
    if not m:
        raise ParseError(f"日付を読めません: {s!r}")
    y, mo, d = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    return date(y, mo, d)


def parse_time(s: str) -> str:
    m = _TIME_RE.search(s or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def parse_side(side_text: str, type_text: str = "") -> Optional[tuple[str, bool, bool]]:
    """(売買の向き, 信用取引か, 返済注文か) を返す。対象外の行は None。

    楽天証券の「売埋」は売建玉の返済＝買い戻し、「買埋」は買建玉の返済＝売り。
    """
    t = _norm(side_text) + "|" + _norm(type_text)
    if any(k in t for k in ("現引", "現渡", "入庫", "出庫", "配当", "分割", "移管")):
        return None
    margin = "信用" in t or "建" in t or "埋" in t or "返済" in t
    is_close = "埋" in t or "返済" in t
    s = _norm(side_text)
    if "売埋" in s:
        return "buy", True, True
    if "買埋" in s:
        return "sell", True, True
    # SBI: 「株式現物買」「信用新規売」「信用返済買」など。最後に出てくる売/買を採用
    last_buy = s.rfind("買")
    last_sell = s.rfind("売")
    if last_buy == -1 and last_sell == -1:
        if s.lower() in ("buy", "b"):
            return "buy", margin, is_close
        if s.lower() in ("sell", "s"):
            return "sell", margin, is_close
        return None
    return ("buy" if last_buy > last_sell else "sell"), margin, is_close


def _guess_market(cols: dict[str, int], row: list[str], header_text: str, symbol: str) -> str:
    if "market" in cols:
        v = _norm(row[cols["market"]]).upper()
        if v in ("US", "米国", "米国株", "USA"):
            return "US"
        if v in ("JP", "日本", "日本株", "JPN"):
            return "JP"
    if "currency" in cols:
        v = _norm(row[cols["currency"]]).upper()
        if "USD" in v or "ドル" in v:
            return "US"
        if "円" in v or "JPY" in v:
            return "JP"
    if "USドル" in header_text or "外貨" in header_text:
        return "US"
    # 日本株コードは 4桁（または 130A のような英数字4文字）
    if re.fullmatch(r"\d{4}|\d{3}[A-Z]", symbol):
        return "JP"
    if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", symbol):
        return "US"
    return "JP"


def parse_file(path: Path) -> tuple[list[Execution], list[str]]:
    text = read_text(path)
    broker = detect_broker(text, path.name)
    rows = list(csv.reader(io.StringIO(text)))
    hidx, cols = _locate_header(rows)
    header_text = ",".join(rows[hidx])
    execs: list[Execution] = []
    warnings: list[str] = []

    def get(row, role, default=""):
        i = cols.get(role)
        return row[i] if i is not None and i < len(row) else default

    for lineno, row in enumerate(rows[hidx + 1 :], start=hidx + 2):
        if not any(c.strip() for c in row):
            continue
        src = f"{path.name}:{lineno}"
        try:
            date_raw = get(row, "date")
            if not _DATE_RE.search(date_raw):
                continue  # 合計行・注記行など
            side = parse_side(get(row, "side"), get(row, "trade_type"))
            if side is None:
                warnings.append(f"{src}: 売買以外の行として読み飛ばしました（{get(row, 'side')}）")
                continue
            symbol = _norm(get(row, "symbol")).upper()
            market = _guess_market(cols, row, header_text, symbol)
            qty = abs(to_number(get(row, "qty")))
            price = to_number(get(row, "price"))
            if qty == 0:
                continue
            fee = abs(to_number(get(row, "fee"))) + abs(to_number(get(row, "fee_tax"))) + abs(
                to_number(get(row, "other_cost"))
            )
            fx: Optional[float]
            if market == "JP":
                fx = 1.0
            else:
                fx = to_number(get(row, "fx")) or None
                if fx is None:
                    jpy = abs(to_number(get(row, "amount_jpy")))
                    usd = abs(to_number(get(row, "amount_usd")))
                    if jpy and usd:
                        fx = jpy / usd
                if fx is None:
                    warnings.append(f"{src}: 為替レートが無いため円換算できません（{symbol}）")
            execs.append(
                Execution(
                    trade_date=parse_date(date_raw),
                    time=parse_time(get(row, "time")) or parse_time(date_raw),
                    market=market,
                    symbol=symbol,
                    name=get(row, "name").strip(),
                    side=side[0],
                    qty=qty,
                    price=price,
                    fee=fee,
                    fx=fx,
                    margin=side[1],
                    account=_norm(get(row, "account")),
                    broker=broker,
                    source=src,
                    memo=get(row, "memo").strip(),
                    is_close=side[2],
                )
            )
        except (ParseError, ValueError) as e:
            warnings.append(f"{src}: 読み込めませんでした（{e}）")
    if not execs:
        warnings.append(f"{path.name}: 約定が1件も読み込めませんでした")
    return execs, warnings
