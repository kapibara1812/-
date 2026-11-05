"""python -m unittest discover -s tests （trade-journal ディレクトリで実行）"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tradelog.matcher import group_daytrades, match  # noqa: E402
from tradelog.parsers import parse_file, parse_side  # noqa: E402
from tradelog.stats import compute  # noqa: E402

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
