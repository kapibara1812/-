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
    "holding_plan": ["保有想定"],
    "exit_rule_timing": ["撤退ラインの決定"],
    "exit_reason": ["決済理由"],
    "entry_type": ["買いのタイプ"],
    "add_on": ["追加買い"],
    "ma25": ["25日線の向き"],
    "event": ["イベント接近"],
    "theme": ["テーマ"],
    "exit_line": ["撤退ライン(円)"],
    "avg_exit": ["avg_exit", "平均決済単価"],
    "exit_low": ["決済日の安値(円)"],
    "exit_close": ["決済日の終値(円)"],
    "holding_days": ["holding_days", "保有日数"],
    "title": ["タイトル", "symbol"],
}

# 項目別の成績を出す対象: (内部キー, 見出し, 複数選択か)
DIMENSIONS = [
    ("holding_plan", "保有想定別", False),
    ("entry_type", "買いのタイプ別", True),
    ("ma25", "買った時の25日線の向き別", False),
    ("add_on", "追加買い別", False),
    ("exit_rule_timing", "撤退ラインを決めた時期別", False),
    ("exit_reason", "決済理由別", False),
    ("event", "イベント接近別", True),
    ("theme", "テーマ別", True),
]


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
        row = {
            "pnl": pnl,
            "exit_date": exit_date,
            "title": str(_get(r, "title") or ""),
            "market": _market_label(_get(r, "market")),
            "style": _get(r, "style") or "不明",
            "tags": _tags(_get(r, "tags")),
            "good_tags": _tags(_get(r, "good_tags")),
        }
        for key, _, multi in DIMENSIONS:
            v = _get(r, key)
            row[key] = _tags(v) if multi else (str(v) if v else None)
        for key in ("exit_line", "avg_exit", "exit_low", "exit_close", "holding_days"):
            row[key] = _num(_get(r, key))
        rows.append(row)
    rows.sort(key=lambda x: x["exit_date"])

    out = {"month": month, "overall": summarize([r["pnl"] for r in rows]), "skipped_no_pnl": skipped}

    for dim in ("market", "style"):
        buckets = defaultdict(list)
        for r in rows:
            buckets[r[dim]].append(r["pnl"])
        out[f"by_{dim}"] = {k: summarize(v) for k, v in sorted(buckets.items())}

    # 追加項目（保有想定・買いのタイプなど）ごとの成績。未入力のトレードは数えない
    out["by_dimension"] = {}
    for key, label, multi in DIMENSIONS:
        buckets = defaultdict(list)
        for r in rows:
            vals = r[key] if multi else ([r[key]] if r[key] else [])
            for v in vals:
                buckets[v].append(r["pnl"])
        if buckets:
            out["by_dimension"][label] = {k: summarize(v) for k, v in sorted(buckets.items())}

    # 撤退ラインどおりに売れたか（撤退ラインと決済単価が入っているトレード）
    exits = []
    for r in rows:
        if r["exit_line"] and r["avg_exit"]:
            exits.append(
                {
                    "title": r["title"],
                    "exit_line": r["exit_line"],
                    "avg_exit": r["avg_exit"],
                    "vs_line": round(r["avg_exit"] - r["exit_line"], 1),
                    "vs_low": round(r["avg_exit"] - r["exit_low"], 1) if r["exit_low"] else None,
                    "vs_close": round(r["avg_exit"] - r["exit_close"], 1) if r["exit_close"] else None,
                    "timing": r["exit_rule_timing"],
                }
            )
    out["exit_execution"] = exits

    # 保有想定と実際の保有期間のずれ（中期・長期のつもりで30日以内に決済）
    mismatch = [
        r for r in rows
        if r["holding_plan"] and ("中期" in r["holding_plan"] or "長期" in r["holding_plan"])
        and r["holding_days"] is not None and r["holding_days"] <= 30
    ]
    planned_long = [r for r in rows if r["holding_plan"] and ("中期" in r["holding_plan"] or "長期" in r["holding_plan"])]
    out["plan_mismatch"] = {
        "planned_long": len(planned_long),
        "closed_within_30d": len(mismatch),
        "pnl_jpy": round(sum(r["pnl"] for r in mismatch)),
    }

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
    for label, d in s.get("by_dimension", {}).items():
        lines += [f"### {label}", "", "| 区分 | 取引数 | 勝率 | 損益 |", "|---|---|---|---|"]
        for k, v in d.items():
            lines.append(f"| {k} | {v['trades']} | {val(v['win_rate_pct'], '%')} | {yen(v['pnl_jpy'])} |")
        lines.append("")
    if s.get("exit_execution"):
        lines += [
            "### 撤退ラインの執行",
            "",
            "| トレード | 撤退ライン | 決済単価 | ラインとの差 | 当日安値との差 | 当日終値との差 | ラインを決めた時期 |",
            "|---|---|---|---|---|---|---|",
        ]
        for e in s["exit_execution"]:
            def d(v):
                return "—" if v is None else f"{v:+,.0f}円"
            lines.append(
                f"| {e['title']} | {e['exit_line']:,.0f}円 | {e['avg_exit']:,.0f}円 | {d(e['vs_line'])} | {d(e['vs_low'])} | {d(e['vs_close'])} | {e['timing'] or '—'} |"
            )
        lines.append("")
    pm = s.get("plan_mismatch")
    if pm and pm["planned_long"]:
        lines += [
            "### 保有想定とのずれ",
            "",
            f"中期・長期のつもりで買った {pm['planned_long']}件のうち、30日以内に決済したのは {pm['closed_within_30d']}件（損益 {yen(pm['pnl_jpy'])}）",
            "",
        ]
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
