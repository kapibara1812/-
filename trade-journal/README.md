# トレード反省ツール

日本株・米国株の売買履歴とチャートを Claude と振り返り、Notion に記録・集計するための仕組み。

- **記録先**: Notion「トレード反省ノート」（トレード記録 DB / 月次振り返り DB）→ [docs/notion-schema.md](docs/notion-schema.md)
- **損益計算**: このフォルダの Python スクリプト（標準ライブラリのみ。インストール不要）
- **作業手順**: Claude Code のスキル（`.claude/skills/`）
  - `trade-import` … CSV を取り込んで Notion に登録
  - `trade-review` … チャートを見て1トレードを反省
  - `trade-monthly-review` … 月次の集計と振り返り

## 使い方（Claude に頼むだけ）

1. 証券会社から約定履歴CSVをダウンロードして Claude に渡し、「取り込んで」と頼む
   - SBI証券・楽天証券の日本株・米国株に対応（Shift_JIS のままでOK）
   - CSVに無い取引は [templates/manual_template.csv](templates/manual_template.csv) の形式で手入力できる
2. チャートのスクリーンショットを貼って「このトレードを反省したい」と頼む
3. 月末に「10月の月次振り返りをして」と頼む

## 計算のルール

- **1トレード** = ポジションを持ってから、決済で数量がゼロに戻るまで（分割エントリー・分割決済は1つにまとめる）
- 同じ銘柄でも 現物/信用、口座区分（特定・NISAなど）が違えば別のポジションとして扱う
- **損益** = 決済代金 − 取得代金 − 手数料（手数料にかかる消費税を含む）。売りから入った信用取引は符号を逆にする
- **米国株** は約定ごとの為替レートで円に換算する（為替損益を含む）。ドル建て損益も別に残す
- **スタイル** は保有日数で自動判定: 当日決済＝デイトレ、30日以内＝スイング、それ以上＝中長期
- 時刻が無いCSVで同じ日に売買がある場合は、新規（買い・信用新規）→ 決済の順とみなす
- 期間内に決済していないポジションは登録せず「未決済」として表示する

## コマンド（Claude が使う）

```
cd trade-journal
python3 -m tradelog import data/*.csv --out data/trades.json   # 取込・損益計算
python3 -m tradelog notion data/trades.json [--group-daytrades] --exclude-file data/registered_ids.txt > data/pages.json
python3 -m tradelog stats data/trades.json --month 2026-10      # 成績集計
python3 -m unittest discover -s tests                          # テスト
```

`data/` は git 管理外。実際の売買データはコミットしない。

## CSVの列が合わないとき

証券会社のCSVの列名は `tradelog/parsers.py` の `ALIASES` で対応付けている。テスト用のサンプル（`tests/fixtures/`）は各社の形式を想定して作ったもので、実物とは細部が違う可能性がある。初回の取り込み時に件数と損益を証券会社の画面と照合し、ずれがあれば `ALIASES` を直す。

## 今後の拡張

- **チャートの自動取得**（日足: J-Quants / 分足: 有料データ）
- **Claude API による自動分析**: [prompts/trade_review.md](prompts/trade_review.md) を指示文としてそのまま使える
