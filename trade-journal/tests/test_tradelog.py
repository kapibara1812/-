"""python -m unittest discover -s tests （trade-journal ディレクトリで実行）"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tradelog.matcher import group_daytrades, match  # noqa: E402
from tradelog.parsers import parse_file, parse_side  # noqa: E402
from tradelog.stats import compute, to_markdown  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def load(*names):
    execs, warns = [], []
    for n in names:
        e, w = parse_file(FX / n)
        execs += e
        warns += w
    return execs, warns


class TestSide(unittest.TestCase):
    def test_sides(self):
        self.assertEqual(parse_side("株式現物買"), ("buy", False, False))
        self.assertEqual(parse_side("信用新規売"), ("sell", True, False))
        self.assertEqual(parse_side("信用返済買"), ("buy", True, True))
        self.assertEqual(parse_side("売埋", "信用返済"), ("sell", True, True))
        self.assertEqual(parse_side("買埋", "信用返済"), ("buy", True, True))
        self.assertEqual(parse_side("買付", "現物"), ("buy", False, False))
        self.assertIsNone(parse_side("現引", "信用返済"))


class TestImport(unittest.TestCase):
    def test_rakuten_jp(self):
        execs, warns = load("rakuten_jp.csv")
        self.assertEqual(len(execs), 4)
        self.assertEqual(execs[0].broker, "楽天証券")
        trades, open_pos, _ = match(execs)
        self.assertEqual([t.pnl_jpy for t in trades], [15000, -8000])
        self.assertEqual(trades[1].direction, "short")
        self.assertEqual(trades[1].style, "デイトレ")
        self.assertFalse(open_pos)

    def test_rakuten_us_jpy_conversion(self):
        execs, _ = load("rakuten_us.csv")
        trades, _, _ = match(execs)
        t = trades[0]
        self.assertEqual(t.market, "US")
        # 1300*152 - 1200*150 - (2.2*150 + 2.2*152)
        self.assertEqual(t.pnl_jpy, round(197600 - 180000 - 664.4))
        self.assertAlmostEqual(t.pnl_local, 100 - 4.4, places=2)
        self.assertEqual(t.style, "中長期")

    def test_sbi_descending_same_day_and_orphan(self):
        execs, _ = load("sbi_jp.csv")
        self.assertEqual(execs[0].broker, "SBI証券")
        trades, _, warns = match(execs)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].pnl_jpy, -10000)
        self.assertTrue(any("9984" in w for w in warns))

    def test_shift_jis_file(self):
        # 証券会社のCSVは Shift_JIS(cp932) で配布されるため、変換して読めることを確認
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            src = (FX / "rakuten_jp.csv").read_text(encoding="utf-8")
            path = Path(d) / "rakuten_sjis.csv"
            path.write_bytes(src.encode("cp932"))
            execs, _ = parse_file(path)
        self.assertEqual(len(execs), 4)
        self.assertEqual(execs[0].name, "トヨタ自動車")

    def test_rakuten_margin_close_with_open_info(self):
        execs, warns = load("rakuten_jp_margin.csv")
        trades, open_pos, w2 = match(execs)
        by = {t.symbol: t for t in trades}
        # 建玉の情報から新規を復元。同じ内容の2行は両方残る（200株のトレード）
        t = by["1111"]
        self.assertEqual(t.direction, "long")
        self.assertEqual(t.qty, 200)
        self.assertEqual(t.pnl_jpy, -10330)
        self.assertEqual(t.broker_pnl, -10330)
        self.assertEqual(t.entry_date.isoformat(), "2026-10-30")
        # 新規の行がCSVにある場合は二重に数えない
        t2 = by["2222"]
        self.assertEqual(t2.pnl_jpy, 4760)
        self.assertEqual(len(t2.fills), 2)
        self.assertFalse(open_pos)
        self.assertTrue(any("3333" in w and "建玉" in w for w in warns))

    def _manual(self, rows):
        import tempfile

        d = tempfile.mkdtemp()
        path = Path(d) / "manual.csv"
        path.write_text("約定日,約定時刻,マーケット,銘柄コード,銘柄名,売買,数量,単価,手数料,為替レート,口座,メモ\n" + "\n".join(rows) + "\n")
        return parse_file(path)[0]

    def test_cash_partial_sell_moving_average(self):
        execs = self._manual([
            "2026/10/01,,JP,9999,テスト,買,100,1000,100,,特定,",
            "2026/10/02,,JP,9999,テスト,買,100,1200,100,,特定,",
            "2026/10/10,,JP,9999,テスト,売,100,1300,100,,特定,",
        ])
        trades, open_pos, _ = match(execs)
        self.assertEqual(len(trades), 1)
        # 平均取得 (200,000+20,000+200)/200 = 1,101 → 130,000-100-110,100
        self.assertEqual(trades[0].pnl_jpy, 19800)
        self.assertEqual(open_pos[0]["position"], 100)

    def test_cash_split(self):
        from datetime import date

        execs = self._manual([
            "2026/08/01,,JP,8888,分割株,買,2,2000,0,,特定,",
            "2026/10/01,,JP,8888,分割株,買,1,900,0,,特定,",
            "2026/11/01,,JP,8888,分割株,売,5,1100,0,,特定,",
        ])
        trades, open_pos, warns = match(execs, [("8888", date(2026, 9, 1), 2)])
        self.assertEqual(trades[0].qty, 5)
        self.assertEqual(trades[0].pnl_jpy, 5500 - 4900)
        self.assertFalse(open_pos)
        self.assertFalse(warns)

    def test_duplicate_files_ignored(self):
        execs, _ = load("rakuten_jp.csv", "rakuten_jp.csv")
        trades, _, _ = match(execs)
        self.assertEqual(len(trades), 2)

    def test_manual_template(self):
        execs, _ = parse_file(ROOT / "templates" / "manual_template.csv")
        trades, _, _ = match(execs)
        self.assertEqual(trades[0].pnl_jpy, 5000)

    def test_stable_ids_and_daytrade_groups(self):
        a, _, _ = match(load("rakuten_jp.csv", "sbi_jp.csv")[0])
        b, _, _ = match(load("sbi_jp.csv", "rakuten_jp.csv")[0])
        self.assertEqual(sorted(t.trade_id for t in a), sorted(t.trade_id for t in b))
        days = group_daytrades(a)
        self.assertEqual([d["date"] for d in days], ["2026-10-15", "2026-10-22"])


class TestStats(unittest.TestCase):
    def test_dimensions_and_exit_execution(self):
        recs = [
            {"タイトル": "A", "損益(円)": -88732, "date:決済日:start": "2026-11-04", "市場": "日本株",
             "保有想定": "長期（半年以上）", "保有日数": 12, "買いのタイプ": '["押し目・サポート反発", "急落の反発狙い"]',
             "追加買い": "含み損で追加（ナンピン）", "撤退ライン(円)": 4936, "平均決済単価": 4930,
             "決済日の安値(円)": 4710, "決済日の終値(円)": 5270, "撤退ラインの決定": "買った後に決めた"},
            {"タイトル": "B", "損益(円)": -66970, "date:決済日:start": "2026-11-04", "市場": "日本株",
             "保有想定": "長期（半年以上）", "保有日数": 5, "買いのタイプ": ["業績・バリュー", "急落の反発狙い"],
             "追加買い": "なし"},
        ]
        s = compute(recs, "2026-11")
        self.assertEqual(s["by_dimension"]["買いのタイプ別"]["急落の反発狙い"]["trades"], 2)
        self.assertEqual(s["by_dimension"]["追加買い別"]["なし"]["pnl_jpy"], -66970)
        e = s["exit_execution"][0]
        self.assertEqual((e["vs_line"], e["vs_low"], e["vs_close"]), (-6, 220, -340))
        self.assertEqual(s["plan_mismatch"], {"planned_long": 2, "closed_within_30d": 2, "pnl_jpy": -155702})
        self.assertIn("撤退ラインの執行", to_markdown(s))

    def test_stats(self):
        recs = [
            {"損益(円)": "10,000", "エグジット日": "2026-10-01", "市場": "日本株", "失敗タグ": []},
            {"損益(円)": -5000, "エグジット日": "2026-10-02", "市場": "日本株", "失敗タグ": ["損切り遅れ"]},
            {"損益(円)": -3000, "エグジット日": "2026-10-03", "市場": "米国株", "失敗タグ": "損切り遅れ, 飛び乗り"},
            {"損益(円)": 1000, "エグジット日": "2026-11-01", "市場": "米国株"},
        ]
        s = compute(recs, "2026-10")
        o = s["overall"]
        self.assertEqual(o["trades"], 3)
        self.assertEqual(o["pnl_jpy"], 2000)
        self.assertEqual(o["profit_factor"], 1.25)
        self.assertEqual(o["max_consecutive_losses"], 2)
        self.assertEqual(o["max_drawdown_jpy"], 8000)
        self.assertEqual(s["failure_tags"][0], {"tag": "損切り遅れ", "count": 2, "pnl_jpy": -8000})


if __name__ == "__main__":
    unittest.main()
