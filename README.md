# QuizFour

`input` フォルダ内のすべての `.csv` をSQLiteへ取り込み、4択問題を出すスマートフォン向けのStreamlitクイズアプリです。

起動時にCSVをチェックし、**未取り込みのCSVファイル名だけ**をDBへ追加します。
出題時のデータ取得はCSVではなくDBから行います。

## 注意

- `input/initial.csv` の列は `Category,English,1,2,3,4,Answer,Japanese` の順番です。

## 機能

- `Category1` を選んで開始
- すべての問題をCSV順に出題するモード
- 出題数を `10` / `20` / `30` またはカスタム（スライダー）で指定
- 英語は常に表示、日本語はメイン画面の設定で表示ON/OFF
- 4択回答、正誤判定、進捗表示、結果表示

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
