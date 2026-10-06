# kaigotool — 介護費用申請自動化

- **Step1**（実装済み）: Gmail から領収書を取得し `介護用品領収書\YYYYMM` に保存
- **Step2**（未実装）: ベネフィット・ステーションの申請フォームへ入力

設計は [docs/design.md](docs/design.md) を参照。

## セットアップ（Windows、初回のみ）

1. **Python 3.11 以上**をインストール（python.org のインストーラで「Add python.exe to PATH」にチェック）
2. このフォルダでコマンドプロンプトを開き、ライブラリをインストール
   ```
   pip install -r requirements.txt
   ```
   ブラウザはインストール済みの Edge を使うので `playwright install` は不要です。
3. **Gmail のアプリ パスワード**を作成
   - Google アカウント → セキュリティ → 2 段階認証プロセスを有効化
   - https://myaccount.google.com/apppasswords で「kaigotool」などの名前で作成し、16 文字のパスワードを控える
   - Gmail の設定 →「メール転送と POP/IMAP」→ IMAP が有効になっていることを確認
4. `config.example.toml` を `config.toml` にコピーし、`address` と `app_password` を記入
   （`config.toml` は git に登録されません）

## Step1 の使い方

```
python step1.py
```

ダイアログで対象年月（既定は前月）と対象業者を選んで「実行」。コマンドで指定することもできます。

```
python step1.py --month 202609                    # 両方
python step1.py --month 202609 --vendor magokoro  # まごころのみ
python step1.py --month 202609 --overwrite        # 既存ファイルも取り直す
python step1.py --month 202609 --show-browser     # まごころの操作を画面に表示（動作確認用）
```

### 出力

| ファイル | 内容 |
| --- | --- |
| `領収書ホームケア_YYYYMM.pdf` | 電子領収書ページを PDF 化 |
| `領収書まごころ_YYYYMM.pdf` | 納品書ダウンロードページから取得 |
| `receipts.json` | 各領収書の日付（ホームケア=ご注文日、まごころ=発行日）・金額（ホームケア=「合計金額」行の小計、まごころ=総合計）。Step2 で使用 |

同じ月に対象メールが複数通ある場合は `_1`, `_2` … の連番になります（受信日時の古い順）。
失敗したメールがあっても残りは続行し、まごころの失敗時は `*.error.png` に画面を保存します。

## テスト

```
pip install pytest
python -m pytest
```

`tests/test_web.py` はローカルの模擬サイトでブラウザ操作を確認します（実サイトには接続しません）。
