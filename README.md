# kaigotool — 介護費用申請自動化

- **Step1**: Gmail から領収書を取得し `介護用品領収書\YYYYMM` に保存
- **Step2**: 領収書 PDF を読み取り、ベネフィット・ステーションの申請フォームへ入力（送信は手動）

Step2 は Step1 と独立して使えます。手動で用意した領収書でも、次の命名規則どおりなら読み込みます。

```
介護用品領収書\YYYYMM\領収書ホームケア_YYYYMM.pdf
介護用品領収書\YYYYMM\領収書まごころ_YYYYMM.pdf
（同じ月に複数あるときは _1, _2 … を付ける。例: 領収書まごころ_202610_1.pdf）
```

設計は [docs/design.md](docs/design.md) を参照。

## セットアップ（Windows、初回のみ）

1. **Python 3.11 以上**をインストール
2. VS Code のターミナル（PowerShell）でライブラリをインストール。
   **プログラムを実行する Python と同じもの**で実行してください（例は python3.14 の場合）:
   ```
   & C:\Users\you50\.local\bin\python3.14.exe -m pip install -r C:\Users\you50\Downloads\kaigotool\requirements.txt
   ```
   ブラウザはインストール済みの Edge を使うので `playwright install` は不要です。
3. `config.example.toml` をコピーして `config.toml` という名前で同じフォルダに保存し、値を記入
   （`config.toml` は git に登録されません）
   - Step2 用: `[application]`（介護対象者・認定期間・口座情報）
   - Step1 用: `[gmail]`（下記のアプリ パスワード）
4. （Step1 を使う場合）**Gmail のアプリ パスワード**を作成
   - Google アカウント → セキュリティ → 2 段階認証プロセスを有効化
   - https://myaccount.google.com/apppasswords で作成し、16 文字のパスワードを `config.toml` に記入
   - Gmail の設定 →「メール転送と POP/IMAP」→ IMAP が有効になっていることを確認

## Step2 の使い方（申請）

```
python step2.py
```

1. 確認画面が開き、当月のフォルダの領収書が一覧表示されます（対象年月は変更・直接入力可）
2. 読み取った**日付・金額を確認**します。読み取れなかった欄（赤字のメモ付き）は手入力してください
   - Microsoft Print to PDF で保存した PDF は文字情報が無い（画像の）ことが多く、自動では読めません。
     Edge の印刷で「**PDF として保存**」を選ぶと文字情報が残り、自動で読み取れます
3. 「申請画面を開いて入力」を押すと Edge が開きます。ログインが必要ならログインしてください
   （ログイン状態は次回以降も保持されます）
4. 「申し込む」→ フォーム入力まで自動で行います。入力できなかった項目はターミナルに表示されます
5. **内容を確認し、「次へ」以降はご自身で操作**してください。終わったらブラウザを閉じます

領収書は 1 件につき 1 枠（①ホームケア、②まごころ、複数あれば③以降）に入力し、
ご申請合計金額は全領収書の合計です。日付・金額の読み取り元:

| 領収書 | 日付 | 金額 |
| --- | --- | --- |
| ホームケア | ご注文日 | 「合計金額」行の小計 |
| まごころ | 発行日 | 総合計 |

## Step1 の使い方（領収書取得）

```
python step1.py                                   # ダイアログで対象年月（既定は当月）と業者を選択
python step1.py --month 202610 --vendor magokoro  # まごころのみ
python step1.py --month 202610 --overwrite        # 既存ファイルも取り直す
python step1.py --month 202610 --show-browser     # まごころの操作を画面に表示（動作確認用）
```

対象年月は実行日から自動計算されるので、年が変わってもそのまま使えます（一覧にない年月も直接入力可）。
同じ月に対象メールが複数通ある場合は `_1`, `_2` … の連番になります（受信日時の古い順）。

## テスト

```
pip install pytest
python -m pytest
```

`tests/test_web.py` / `tests/test_step2_web.py` はローカルの模擬サイトでブラウザ操作を確認します（実サイトには接続しません）。
