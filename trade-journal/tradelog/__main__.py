"""コマンドライン入口。

    python -m tradelog import <CSV...> [--out trades.json]
    python -m tradelog notion <trades.json> [--group-daytrades] [--exclude ID,ID]
    python -m tradelog stats <trades.json> [--month 2026-10]

trade-journal ディレクトリで実行する。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .matcher import group_daytrades, match
from .notion_payload import build_pages
from .parsers import ParseError, parse_file
from .stats import compute, to_markdown


def _yen(v):
    return "—" if v is None else f"{v:+,.0f}円"


def cmd_import(args) -> int:
    execs, warnings = [], []
    brokers = {}
    for p in args.files:
        path = Path(p)
        try:
            e, w = parse_file(path)
        except ParseError as err:
            print(f"[エラー] {path.name}: {err}", file=sys.stderr)
            return 1
        execs += e
        warnings += w
        brokers[path.name] = {"broker": e[0].broker if e else "不明", "executions": len(e)}

    trades, open_positions, w2 = match(execs)
    warnings += w2
    result = {
        "files": brokers,
        "trades": [t.to_dict() for t in trades],
        "daytrade_days": group_daytrades(trades),
        "open_positions": open_positions,
        "warnings": warnings,
        "summary": compute([t.to_dict() for t in trades])["overall"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"# 取込結果（{out}）\n")
    for name, info in brokers.items():
        print(f"- {name}: {info['broker']} / 約定 {info['executions']}件")
    print(f"\n決済済みトレード: {len(trades)}件 / 未決済: {len(open_positions)}件\n")
    if trades:
        print("| 決済日 | 市場 | 銘柄 | 方向 | スタイル | 保有日数 | 損益(円) | 損益率 |")
        print("|---|---|---|---|---|---|---|---|")
        for t in trades:
            d = t.to_dict()
            pct = "—" if t.return_pct is None else f"{t.return_pct:+.2f}%"
            print(
                f"| {d['exit_date']} | {d['market_label']} | {t.symbol} {t.name} | {d['direction_label']} "
                f"| {t.style} | {t.holding_days} | {_yen(t.pnl_jpy)} | {pct} |"
            )
        s = result["summary"]
        print(f"\n合計 {_yen(s['pnl_jpy'])} / 勝率 {s['win_rate_pct']}%")
        checked = [t for t in trades if t.broker_pnl is not None and t.pnl_jpy is not None]
        if checked:
            diff = [t for t in checked if abs(t.broker_pnl - t.pnl_jpy) > 1]
            print(f"\n照合: 証券会社のCSVに損益が書かれている {len(checked)}件のうち、一致 {len(checked) - len(diff)}件")
            for t in diff:
                print(f"- 不一致 {t.exit_date} {t.symbol}: 計算 {_yen(t.pnl_jpy)} / CSV {_yen(t.broker_pnl)}")
    if open_positions:
        print("\n## 未決済（今回は登録しません）")
        for p in open_positions:
            print(f"- {p['symbol']} {p['name']} 建玉 {p['position']:+g}（{p['since']}〜）")
    if warnings:
        print("\n## 警告")
        for w in warnings:
            print(f"- {w}")
    return 0


def cmd_notion(args) -> int:
    data = json.loads(Path(args.file).read_text())
    exclude = {x.strip() for x in (args.exclude or "").split(",") if x.strip()}
    if args.exclude_file:
        exclude |= {x.strip() for x in Path(args.exclude_file).read_text().split() if x.strip()}
    pages = build_pages(data, group_daytrades=args.group_daytrades, exclude_ids=exclude)
    print(json.dumps(pages, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args) -> int:
    data = json.loads(Path(args.file).read_text())
    records = data["trades"] if isinstance(data, dict) else data
    s = compute(records, args.month)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(s))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tradelog", description="トレード反省ツール")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import", help="証券会社CSV・手入力CSVを取り込んでトレードにまとめる")
    a.add_argument("files", nargs="+")
    a.add_argument("--out", default="data/trades.json")
    a.set_defaults(func=cmd_import)
    n = sub.add_parser("notion", help="Notion「トレード記録」に登録するページデータを出力する")
    n.add_argument("file", help="import の出力JSON")
    n.add_argument("--group-daytrades", action="store_true", help="デイトレを1日1ページにまとめる")
    n.add_argument("--exclude", help="登録済みの取引ID（カンマ区切り）")
    n.add_argument("--exclude-file", help="登録済みの取引IDを並べたファイル")
    n.set_defaults(func=cmd_notion)
    b = sub.add_parser("stats", help="トレードの成績を集計する")
    b.add_argument("file", help="import の出力JSON、またはトレードのリスト(JSON)")
    b.add_argument("--month", help="YYYY-MM（その月に決済したトレードだけ集計）")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_stats)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
