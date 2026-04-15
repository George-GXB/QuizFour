# QuizFour

`input` フォルダ内のすべての `.csv` をSQLiteへ取り込み、4択問題を出すスマートフォン向けのStreamlitクイズアプリです。

起動時にCSVをチェックし、**未取り込みのCSVファイル名だけ**をDBへ追加します。
出題時のデータ取得はCSVではなくDBから行います。

## 注意

- `input/initial.csv` の列は `Category,English,1,2,3,4,Answer,Japanese` の順番です。

## 主な機能

- ユーザー登録・選択（ユーザー名のみ、ニックネーム等は不要）
- `Category` を選んで出題範囲を絞り込み
- 出題モード：
  - おすすめ（未出題を優先。不足分は正解率が低い順に補充）
  - シャッフル
  - 順番通り
  - 順番通り（出題回数が少ない順）
- 出題数を `10` / `20` / `30` / `50` / `全部` から選択
- 英語は常に表示、日本語はON/OFF切替
- 4択回答、正誤判定、進捗表示、結果表示
- 学習成績のリセット、DB再構築、正解データのCSV反映
- `initial.csvからDBを更新する` ボタンでDBを初期CSVから再構築

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 起動

```bash
streamlit run app.py
```

## テスト

```bash
pytest -q
```
