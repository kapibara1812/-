"""成績の集計（月次振り返り用）。

入力はトレードのリスト（dict）。`import` コマンドの出力JSONの trades か、
Notion から取り出したレコード（日本語の列名でも可）を受け付ける。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Optional

# Notion のプロパティ名 -> 内部キー
FIELD_ALIASES = {
    "pnl_jpy": ["pnl_jpy", "損益(円)", "損益（円）", "損益"],
    "exit_date": ["exit_date", "date:決済日:start", "決済日", "エグジット日"],
    "market": ["market_label", "market", "市場"],
    "style": ["style", "スタイル"],
    "tags": ["tags", "失敗タグ"],
    "good_tags": ["good_tags", "良かったタグ"],
}


def _get(rec: dict, key: str):
    for k in FIELD_ALIASES[key]:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("¥", "").replace("円", "").replace("￥", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _tags(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if s.startswith("["):
        import json

        try:
            return [str(x) for x in json.loads(s)]
        except ValueError:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def _market_label(v) -> str:
    return {"JP": "日本株", "US": "米国株"}.get(v, v or "不明")


def summarize(pnls: list[float]) -> dict:
    wins = [p for p in pnls if p > 0.5]
    losses = [p for p in pnls if p < -0.5]
    n = len(pnls)
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    # 最大連敗・最大ドローダウン（決済順の累積損益ベース）
    streak = max_streak = 0
    equity = peak = max_dd = 0.0
    for p in pnls:
        streak = streak + 1 if p < -0.5 else 0
        max_streak = max(max_streak, streak)
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else None,
        "pnl_jpy": round(sum(pnls)),
        "avg_win_jpy": round(avg_win),
        "avg_loss_jpy": round(avg_loss),
        "payoff_ratio": round(avg_win / avg_loss, 2) if avg_loss else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "expectancy_jpy": round(sum(pnls) / n) if n else None,
        "best_jpy": round(max(pnls)) if pnls else None,
        "worst_jpy": round(min(pnls)) if pnls else None,
        "max_consecutive_losses": max_streak,
        "max_drawdown_jpy": round(max_dd),
    }


def compute(records: Iterable[dict], month: Optional[str] = None) -> dict:
    """month を "YYYY-MM" で指定するとその月に決済したトレードだけを集計する。"""
    rows = []
    skipped = 0
    for r in records:
        pnl = _num(_get(r, "pnl_jpy"))
        exit_date = str(_get(r, "exit_date") or "")[:10]
        if pnl is None:
            skipped += 1
            continue
        if month and not exit_date.startswith(month):
            continue
        rows.append(
            {
                "pnl": pnl,
                "exit_date": exit_date,
                "market": _market_label(_get(r, "market")),
                "style": _get(r, "style") or "不明",
                "tags": _tags(_get(r, "tags")),
                "good_tags": _tags(_get(r, "good_tags")),
            }
        )
    rows.sort(key=lambda x: x["exit_date"])

    out = {"month": month, "overall": summarize([r["pnl"] for r in rows]), "skipped_no_pnl": skipped}

    for dim in ("market", "style"):
        buckets = defaultdict(list)
        for r in rows:
            buckets[r[dim]].append(r["pnl"])
        out[f"by_{dim}"] = {k: summarize(v) for k, v in sorted(buckets.items())}

    monthly = defaultdict(list)
    for r in rows:
        monthly[r["exit_date"][:7]].append(r["pnl"])
    out["by_month"] = {k: summarize(v) for k, v in sorted(monthly.items())}

    tag_count = Counter()
    tag_pnl = defaultdict(float)
    for r in rows:
        for t in r["tags"]:
            tag_count[t] += 1
            tag_pnl[t] += r["pnl"]
    out["failure_tags"] = [
        {"tag": t, "count": c, "pnl_jpy": round(tag_pnl[t])} for t, c in tag_count.most_common()
    ]
    good = Counter(t for r in rows for t in r["good_tags"])
    out["good_tags"] = [{"tag": t, "count": c} for t, c in good.most_common()]
    return out


def to_markdown(s: dict) -> str:
    o = s["overall"]

    def yen(v):
        return "—" if v is None else f"{v:+,.0f}円"

    def val(v, suffix=""):
        return "—" if v is None else f"{v}{suffix}"

    lines = [f"## 成績サマリー{'（' + s['month'] + '）' if s.get('month') else ''}", ""]
    lines += [
        "| 項目 | 値 |",
        "|---|---|",
        f"| 取引数 | {o['trades']}（勝ち {o['wins']} / 負け {o['losses']}） |",
        f"| 勝率 | {val(o['win_rate_pct'], '%')} |",
        f"| 損益合計 | {yen(o['pnl_jpy'])} |",
        f"| 平均利益 / 平均損失 | {yen(o['avg_win_jpy'])} / {yen(-o['avg_loss_jpy'] if o['losses'] else None)} |",
        f"| ペイオフレシオ | {val(o['payoff_ratio'])} |",
        f"| プロフィットファクター | {val(o['profit_factor'])} |",
        f"| 1トレードあたり期待値 | {yen(o['expectancy_jpy'])} |",
        f"| 最大利益 / 最大損失 | {yen(o['best_jpy'])} / {yen(o['worst_jpy'])} |",
        f"| 最大連敗 | {o['max_consecutive_losses']}回 |",
        f"| 最大ドローダウン | {yen(-o['max_drawdown_jpy'] if o['max_drawdown_jpy'] else 0)} |",
        "",
    ]
    for dim, title in (("by_market", "市場別"), ("by_style", "スタイル別")):
        if s[dim]:
            lines += [f"### {title}", "", "| 区分 | 取引数 | 勝率 | 損益 | PF |", "|---|---|---|---|---|"]
            for k, v in s[dim].items():
                lines.append(
                    f"| {k} | {v['trades']} | {val(v['win_rate_pct'], '%')} | {yen(v['pnl_jpy'])} | {val(v['profit_factor'])} |"
                )
            lines.append("")
    if len(s["by_month"]) > 1:
        lines += ["### 月別推移", "", "| 月 | 取引数 | 勝率 | 損益 |", "|---|---|---|---|"]
        for k, v in s["by_month"].items():
            lines.append(f"| {k} | {v['trades']} | {val(v['win_rate_pct'], '%')} | {yen(v['pnl_jpy'])} |")
        lines.append("")
    if s["failure_tags"]:
        lines += ["### 失敗パターン", "", "| タグ | 回数 | 該当トレードの損益 |", "|---|---|---|"]
        for t in s["failure_tags"]:
            lines.append(f"| {t['tag']} | {t['count']} | {yen(t['pnl_jpy'])} |")
        lines.append("")
    if s["good_tags"]:
        lines += ["### 良かった点", "", "| タグ | 回数 |", "|---|---|"]
        for t in s["good_tags"]:
            lines.append(f"| {t['tag']} | {t['count']} |")
        lines.append("")
    return "\n".join(lines)
