"""Step2: ベネフィット・ステーションで申請フォームに入力する（送信はしない）。

ツールが起動・操作するブラウザは Cloudflare の認証で弾かれるため、次の方式にしている。
  1. 「申請用 Edge を開く」で普通の Edge を起動（外部から操作できる設定 = リモートデバッグを有効にして起動）
  2. ユーザーがその Edge でログインし、申込画面を開く（人が操作するので Cloudflare を通過できる）
  3. 「開いている申請画面に入力」で、その Edge に接続して入力する
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .form import Field, fill_fields
from .web import buttons, find_visible

CDP_PORT = 9222
FORM_HEADING = "店舗・施設からの質問事項"

EDGE_CANDIDATES = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
]


def profile_dir() -> Path:
    """申請用 Edge のプロファイル（普段の Edge とは別。ログイン状態はここに残る）。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "kaigotool" / "edge-profile"


def edge_path() -> str | None:
    for c in EDGE_CANDIDATES:
        p = os.path.expandvars(c)
        if os.path.isfile(p):
            return p
    return shutil.which("msedge")


def launch_edge(url: str, port: int = CDP_PORT, exe: str | None = None, extra_args: list[str] | None = None) -> None:
    exe = exe or edge_path()
    if not exe:
        raise RuntimeError("Microsoft Edge が見つかりません")
    profile_dir().mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir()}",
            "--no-first-run", "--no-default-browser-check", *(extra_args or []), url]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("申請用の Edge を開きました。ログインして、申込プランの画面（または申込入力画面）を開いてください。")
    print("開けたら「開いている申請画面に入力」を押してください。")


def _find_page(browser, host: str):
    """host のページのうち、申込入力画面 → 申込プラン画面 の順で優先して返す。"""
    pages = [p for c in browser.contexts for p in c.pages if host and host in (urlparse(p.url).hostname or "")]
    for p in reversed(pages):
        if p.get_by_text(FORM_HEADING).count():
            return p
    return pages[-1] if pages else None


def fill_page(page, fields: list[Field]) -> list:
    """申込入力画面ならそのまま、申込プラン画面なら「申し込む」を押してから入力する。"""
    if not page.get_by_text(FORM_HEADING).count():
        find_visible(page, buttons(page, ["申し込む"]), 10_000,
                     "申込入力画面または「申し込む」ボタン（申込プランの画面を開いてください）").click()
        page.get_by_text(FORM_HEADING).first.wait_for(timeout=60_000)
    _scroll_through(page)
    return fill_fields(page, fields)


def _scroll_through(page) -> None:
    """遅延表示される項目があっても描画されるよう、一度最下部までスクロールする。"""
    for _ in range(30):
        at_bottom = page.evaluate(
            "() => { window.scrollBy(0, window.innerHeight);"
            " return window.innerHeight + window.scrollY >= document.body.scrollHeight - 2; }"
        )
        page.wait_for_timeout(150)
        if at_bottom:
            break
    page.evaluate("() => window.scrollTo(0, 0)")


def fill_open_window(url: str, fields: list[Field], port: int = CDP_PORT) -> int:
    """「申請用 Edge を開く」で開いた Edge に接続して入力する。Edge は開いたまま残す。"""
    from playwright.sync_api import sync_playwright

    print("入力する内容:")
    for f in fields:
        if f.kind == "file":
            print(f"  [添付] {f.label}: {f.value}")
        elif f.kind != "radio":
            print(f"  {f.label}: {f.value}")

    host = urlparse(url).hostname or ""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=10_000)
        except Exception:
            print("× 申請用の Edge に接続できません。")
            print("  先に「申請用 Edge を開く」を押し、開いた Edge でログインしてください。")
            print("  （普段の Edge がこのツールの Edge と同じ設定で既に開いている場合は、一度すべて閉じてから再度お試しください）")
            return 1
        page = _find_page(browser, host)
        if page is None:
            print(f"× 申請用の Edge に {host} のページが開かれていません。ログインして申込プランの画面を開いてください。")
            return 1
        page.bring_to_front()
        try:
            failures = fill_page(page, fields)
        except Exception as e:
            print(f"× 自動入力を中断しました: {e}")
            return 1
    # ここで接続だけ切れる（Edge は開いたまま）

    if failures:
        print("\n▲ 次の項目は自動入力できませんでした。ブラウザで入力してください:")
        for f, reason in failures:
            print(f"  - {f.label}: {f.value}  （{reason}）")
    else:
        print("\n○ 入力が完了しました。")
    print("内容を確認し、「次へ」以降の操作は Edge でご自身で行ってください。")
    return 0 if not failures else 1
