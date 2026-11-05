"""データモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


MARKET_LABELS = {"JP": "日本株", "US": "米国株"}


@dataclass
class Execution:
    """1件の約定（CSVの1行）。"""

    trade_date: date
    time: str  # "HH:MM" または ""（不明）
    market: str  # "JP" | "US"
    symbol: str
    name: str
    side: str  # "buy" | "sell"
    qty: float
    price: float  # 現地通貨建ての単価
    fee: float  # 現地通貨建ての手数料＋手数料にかかる税
    fx: Optional[float]  # 円換算レート（JPは1.0、USで不明ならNone）
    margin: bool  # 信用取引か
    account: str  # 特定/一般/NISA など（不明なら ""）
    broker: str  # "SBI証券" | "楽天証券" | "手入力"
    source: str  # 取込元ファイル名:行番号
    memo: str = ""
    is_close: bool = False  # 信用の返済（決済）注文か

    @property
    def currency(self) -> str:
        return "JPY" if self.market == "JP" else "USD"

    @property
    def sort_key(self):
        return (self.trade_date, self.time or "99:99", self.source)


@dataclass
class Trade:
    """ポジションを持ってから決済でゼロに戻るまでの1トレード。"""

    trade_id: str
    market: str
    symbol: str
    name: str
    direction: str  # "long" | "short"
    margin: bool
    account: str
    broker: str
    entry_date: date
    exit_date: date
    holding_days: int
    style: str  # デイトレ / スイング / 中長期
    qty: float  # 最大建玉数量
    avg_entry: float
    avg_exit: float
    currency: str
    pnl_local: float  # 現地通貨建て損益（手数料控除後）
    pnl_jpy: Optional[float]  # 円換算損益（手数料控除後）
    fees_jpy: Optional[float]
    entry_cost_jpy: Optional[float]
    return_pct: Optional[float]  # 損益 ÷ 取得額（%）
    result: str  # 勝ち / 負け / 引き分け
    fills: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_date"] = self.entry_date.isoformat()
        d["exit_date"] = self.exit_date.isoformat()
        d["exit_month"] = self.exit_date.strftime("%Y-%m")
        d["market_label"] = MARKET_LABELS.get(self.market, self.market)
        d["direction_label"] = "買い" if self.direction == "long" else "売り（空売り）"
        d["margin_label"] = "信用" if self.margin else "現物"
        return d
