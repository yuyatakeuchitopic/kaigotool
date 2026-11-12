# 介護費用申請ツール v2（Python 不要版）

v1 と同じ機能で、画面を見やすくし、**Python が入っていない PC でも動く exe 版**にしたものです。

## はじめて使うとき

1. 次のリンクから zip をダウンロードします（約 80MB）  
   https://github.com/yuyatakeuchitopic/kaigotool/releases/latest/download/kaigotool-v2-windows.zip
2. zip を右クリック →「すべて展開」。展開してできた **`kaigotool` フォルダ**を好きな場所に置きます
   （例: `C:\アプリケーション\kaigotool-v2\kaigotool`）
3. `kaigotool` フォルダの中の **`kaigotool.exe`** をダブルクリック

- 初回は Windows の「PC が保護されました」（SmartScreen）が出ることがあります。
  署名のないアプリのためです。「詳細情報」→「実行」で起動できます。
- **Microsoft Edge** が必要です（Windows 標準で入っています）。
- 設定（申請者情報など）と申請用 Edge のログイン状態は v1 と共通です
  （`%LOCALAPPDATA%\kaigotool`）。v1 で保存済みならそのまま使えます。

## 最新版への更新

ツールを閉じてから、`kaigotool` フォルダの **`update.bat`** をダブルクリックします。
画面上部のタイトル横の版（例: `v2 (2026-11-12)`）が新しくなっていることを確認してください。

## 画面

- **Step1 領収書を取得** … 対象年月とサイトを選んで「領収書を取得」
- **Step2 申請サイトに入力** … 領収書と金額 → ファイル添付 → ①申請用 Edge を開く → ②入力
- **設定** … 申請者情報・口座・フォルダ・Gmail・電話番号・申請サイト URL。「設定を保存」で次回の既定値に

## Python 版として動かす場合（開発用）

このフォルダ（`v2`）で `start.bat` を実行します。exe は GitHub Actions（`.github/workflows/build-v2-windows.yml`）が
Windows 上で作り、作った exe で動作確認（`kaigotool.exe --selftest 結果.txt`）してからリリースに置いています。
