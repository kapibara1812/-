"""取込結果を Notion「トレード記録」DBへ登録するためのページデータに変換する。

出力は Notion MCP の notion-create-pages にそのまま渡せる形:
    [{"properties": {...}, "content": "..."}, ...]
プロパティ名は Notion 側DBの列名と一致させること（docs/notion-schema.md）。
"""

from __future__ import annotations

SIDE_LABEL = {"long": "買い", "short": "売り（空売り）"}

REVIEW_TEMPLATE = """## エントリー根拠
（なぜ入ったか。見ていた時間足・シグナル）

## チャート
（チャートのスクリーンショットを貼る）

## 良かった点
-

## 悪かった点
-

## 次回気をつけること
-
"""


def _fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, int) else f"{v:,.{digits}f}"


def _fills_table(fills: list[dict], currency: str) -> str:
    unit = "円" if currency == "JPY" else "USD"
    lines = [
        "## 約定明細",
        "",
        f"| 約定日 | 時刻 | 売買 | 数量 | 単価({unit}) | 手数料・金利等({unit}) | 為替 |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in fills:
        fx = "" if currency == "JPY" else _fmt(f.get("fx"))
        lines.append(
            f"| {f['date']} | {f.get('time') or ''} | {f['side']} | {_fmt(f['qty'])} | {_fmt(f['price'])} | {_fmt(f['fee'])} | {fx} |"
        )
    return "\n".join(lines)


def trade_page(t: dict) -> dict:
    title = f"{t['exit_date']} {t['symbol']} {t['name']} {SIDE_LABEL[t['direction']]}".replace("  ", " ")
    props = {
        "タイトル": title,
        "date:決済日:start": t["exit_date"],
        "date:決済日:is_datetime": 0,
        "date:エントリー日:start": t["entry_date"],
        "date:エントリー日:is_datetime": 0,
        "決済月": t["exit_date"][:7],
        "市場": t["market_label"],
        "銘柄コード": t["symbol"],
        "銘柄名": t["name"],
        "方向": SIDE_LABEL[t["direction"]],
        "区分": t["margin_label"],
        "スタイル": t["style"],
        "記録単位": "個別トレード",
        "勝敗": t["result"],
        "保有日数": t["holding_days"],
        "数量": t["qty"],
        "平均取得単価": t["avg_entry"],
        "平均決済単価": t["avg_exit"],
        "反省ステータス": "未反省",
        "証券会社": t["broker"] if t["broker"] in ("SBI証券", "楽天証券", "手入力") else "手入力",
        "取引ID": t["trade_id"],
    }
    if t.get("pnl_jpy") is not None:
        props["損益(円)"] = t["pnl_jpy"]
    if t.get("fees_jpy") is not None:
        props["手数料(円)"] = t["fees_jpy"]
    if t.get("return_pct") is not None:
        props["損益率(%)"] = t["return_pct"]
    if t["currency"] == "USD":
        props["損益(USD)"] = t["pnl_local"]
    content = REVIEW_TEMPLATE + "\n" + _fills_table(t["fills"], t["currency"])
    bought = sum(f["qty"] for f in t["fills"] if f["side"] == "買")
    if t["margin_label"] == "現物" and bought - t["qty"] > 1e-9:
        content += (
            f"\n\n保有{_fmt(bought)}株のうち{_fmt(t['qty'])}株を売却。"
            "取得単価は保有株の平均（手数料込み）で計算しています。"
        )
    return {"properties": props, "content": content}


def daytrade_day_page(day: dict, trades_by_id: dict) -> dict:
    ts = [trades_by_id[i] for i in day["trade_ids"]]
    market_label = ts[0]["market_label"]
    title = f"{day['date']} デイトレ（{market_label}・{day['trades']}回）"
    props = {
        "タイトル": title,
        "date:決済日:start": day["date"],
        "date:決済日:is_datetime": 0,
        "date:エントリー日:start": day["date"],
        "date:エントリー日:is_datetime": 0,
        "決済月": day["date"][:7],
        "市場": market_label,
        "銘柄コード": ", ".join(sorted({t["symbol"] for t in ts})),
        "スタイル": "デイトレ",
        "記録単位": "デイトレ日次",
        "取引回数": day["trades"],
        "保有日数": 0,
        "反省ステータス": "未反省",
        "取引ID": day["day_id"],
    }
    if day["pnl_jpy"] is not None:
        props["損益(円)"] = day["pnl_jpy"]
        props["勝敗"] = "勝ち" if day["pnl_jpy"] > 0 else "負け" if day["pnl_jpy"] < 0 else "引き分け"
        fees = [t["fees_jpy"] for t in ts if t.get("fees_jpy") is not None]
        if fees:
            props["手数料(円)"] = sum(fees)
    brokers = {t["broker"] for t in ts}
    if len(brokers) == 1 and next(iter(brokers)) in ("SBI証券", "楽天証券", "手入力"):
        props["証券会社"] = next(iter(brokers))
    rows = [
        "## この日の取引",
        "",
        "| 銘柄 | 方向 | 数量 | 取得 | 決済 | 損益(円) | 勝敗 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in ts:
        rows.append(
            f"| {t['symbol']} {t['name']} | {SIDE_LABEL[t['direction']]} | {_fmt(t['qty'])} | {_fmt(t['avg_entry'])} "
            f"| {_fmt(t['avg_exit'])} | {_fmt(t['pnl_jpy'], 0)} | {t['result']} |"
        )
    rows.append(f"\n勝ち {day['wins']} / 負け {day['losses']}")
    content = REVIEW_TEMPLATE + "\n" + "\n".join(rows)
    return {"properties": props, "content": content}


def build_pages(result: dict, group_daytrades: bool = False, exclude_ids: set | None = None) -> list[dict]:
    exclude_ids = exclude_ids or set()
    trades = result["trades"]
    by_id = {t["trade_id"]: t for t in trades}
    pages = []
    grouped = set()
    if group_daytrades:
        for day in result.get("daytrade_days", []):
            grouped.update(day["trade_ids"])
            if day["day_id"] not in exclude_ids:
                pages.append(daytrade_day_page(day, by_id))
    for t in trades:
        if t["trade_id"] in grouped or t["trade_id"] in exclude_ids:
            continue
        pages.append(trade_page(t))
    pages.sort(key=lambda p: p["properties"]["date:決済日:start"])
    return pages
