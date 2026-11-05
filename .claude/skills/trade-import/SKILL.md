---
name: trade-import
description: SBI証券・楽天証券の約定履歴CSV（日本株・米国株）や手入力CSVを取り込み、損益を計算して Notion「トレード記録」DBに登録する。ユーザーが売買履歴CSVを渡してきたとき、「取り込んで」「登録して」と言われたときに使う。
---

# 売買履歴の取り込み

Notion の ID は `trade-journal/docs/notion-schema.md` を参照（トレード記録 data source: `collection://2f166534-a101-4545-8501-994fdf145f68`）。

## 手順

1. **CSVを置く**: 受け取ったCSVを `trade-journal/data/` に保存する（このフォルダは git 管理外。コミットしない）。
2. **取り込み**: `trade-journal` ディレクトリで実行する。
   ```
   python3 -m tradelog import data/<ファイル>.csv [data/<ファイル2>.csv ...] --out data/trades.json
   ```
   - 複数ファイル（日本株＋米国株、複数月）はまとめて渡す。同じ約定の重複は自動で除かれる。
   - 出力された表と「警告」をユーザーに見せる。
3. **警告への対応**:
   - 「見出し行が見つかりません」→ CSVの先頭20行ほどを確認し、`tradelog/parsers.py` の `ALIASES` に列名を追加して再実行する。追加したらテスト（`python3 -m unittest discover -s tests`）も通す。
   - 「決済に対応する新規の約定がありません」→ 建てた月のCSVを追加でもらうか、`templates/manual_template.csv` の形式で手入力してもらう。
   - 「為替レートが無い」→ 米国株の円換算ができない。CSVに為替の列があるか確認する。
4. **登録単位を確認**: デイトレが多い場合（目安: 月100回以上、または本人の希望）は `--group-daytrades` でデイトレを1日1ページにまとめる。初回は本人に確認し、決めた方針はこのファイルの末尾「運用メモ」に追記する。
5. **重複チェック**: 登録済みの取引IDを Notion から取得する。
   - `notion-query-data-sources` の rows モードで、決済日が今回のCSVの最も古い決済日以降の行を取得し、`取引ID` を集める（100件を超えるときはページを分けて取得）。
   - 取得したIDを `data/registered_ids.txt` に1行1件で保存する。
6. **ページデータの生成**:
   ```
   python3 -m tradelog notion data/trades.json [--group-daytrades] --exclude-file data/registered_ids.txt > data/pages.json
   ```
7. **Notion に登録**: `data/pages.json` の配列を `notion-create-pages` に渡す（parent は上記 data source、1回100件まで）。プロパティ名や値は加工しない。
8. **報告**: 登録件数、合計損益、未決済のポジション、警告をまとめて伝え、「未反省」ビューから反省を始められることを案内する。

## 注意

- 損益の計算はスクリプトの結果だけを使う。自分で暗算した数字を登録しない。
- 実際の売買データ（CSV・JSON）はリポジトリにコミットしない。
- 列の対応はサンプルを基に作った仮のものなので、実物のCSVで初めて取り込むときは、表示された件数・損益を本人の証券会社の画面と照合してもらう。

## 運用メモ

（デイトレをまとめるかなど、決まった運用ルールをここに追記する）
