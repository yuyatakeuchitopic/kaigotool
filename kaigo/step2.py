"""Step2: ベネフィット・ステーションで申請フォームに入力する（送信はしない）。"""

from __future__ import annotations

import os
from pathlib import Path

from .form import Field, fill_fields
from .web import buttons, find_visible

LOGIN_TIMEOUT_MS = 15 * 60 * 1000
FORM_HEADING = "店舗・施設からの質問事項"


def profile_dir() -> Path:
    """ログイン状態を保持する Edge プロファイル（普段の Edge とは別）。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "kaigotool" / "edge-profile"


def open_and_fill(page, url: str, fields: list[Field]) -> list:
    """申込ページ → (ログイン待ち) →「申し込む」→ フォーム入力。入力できなかった項目を返す。"""
    page.goto(url, wait_until="domcontentloaded")

    print("ログインが必要な場合はブラウザでログインしてください（最大 15 分待ちます）。")
    print("ログイン後に申込プランの画面が出なければ、その画面まで移動してください。")
    find_visible(page, buttons(page, ["申し込む"]), LOGIN_TIMEOUT_MS, "「申し込む」ボタン").click()

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


def run(url: str, fields: list[Field], browser_channel: str | None) -> int:
    from playwright.sync_api import sync_playwright

    print("入力する内容:")
    for f in fields:
        if f.kind != "radio":
            print(f"  {f.label}: {f.value}")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir()), channel=browser_channel or None, headless=False, no_viewport=True, locale="ja-JP"
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            failures = open_and_fill(page, url, fields)
        except Exception as e:
            print(f"\n× 自動入力を中断しました: {e}")
            failures = None

        if failures:
            print("\n▲ 次の項目は自動入力できませんでした。ブラウザで入力してください:")
            for f, reason in failures:
                print(f"  - {f.label}: {f.value}  （{reason}）")
        elif failures is not None:
            print("\n○ 入力が完了しました。")
        print("\n内容を確認し、「次へ」以降の操作はブラウザでご自身で行ってください。")
        print("申請が終わったらブラウザを閉じてください。")
        try:
            context.wait_for_event("close", timeout=0)
        except Exception:
            pass
    print("ブラウザが閉じられました。")
    return 0 if failures == [] else 1
