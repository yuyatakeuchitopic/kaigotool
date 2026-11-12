"""exe 版の動作確認（ビルド後に自動で実行する）。

  kaigotool.exe --selftest 結果ファイル.txt

部品の読み込み・Edge の起動・PDF の作成と読み取り・画面部品を、画面と同じく別スレッドで
確認する。結果をファイルに書き、すべて成功なら 0、失敗があれば 1 を返す。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import threading
import traceback
from pathlib import Path


def _browser_and_pdf(channel: str | None) -> str:
    from playwright.sync_api import sync_playwright

    from .receipts import pdf_text

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=channel, headless=True)
        page = browser.new_page()
        page.set_content("<p>selftest 発行日: 2026-01-02</p><p>総合計 ￥1,234</p>")
        data = page.pdf()
        browser.close()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "selftest.pdf"
        path.write_bytes(data)
        text = pdf_text(path)
    if "selftest" not in text:
        raise RuntimeError(f"PDF の文字を読み取れません: {text!r}")
    return f"PDF {len(data):,} バイトを作成し読み取り"


MODULES = ["attachments", "extract", "form", "gui", "mail", "receipts", "settings", "step1", "step2", "web"]


def _imports() -> str:
    import importlib

    for name in MODULES:
        importlib.import_module(f"{__package__}.{name}")
    return f"{len(MODULES)} モジュール"


def _tk() -> str:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    version = root.tk.call("info", "patchlevel")
    root.destroy()
    return f"Tk {version}"


def _gui() -> str:
    """実際の画面を作り、使われた文字・大きさと、保存ボタンが見えるかを確認する。"""
    import tkinter as tk

    from . import gui

    with tempfile.TemporaryDirectory() as d:
        root = tk.Tk()
        try:
            app = gui.App(root, settings_file=Path(d) / "settings.json")
            app.nb.select(2)
            root.update()
            bottom = app.save_btn.winfo_rooty() + app.save_btn.winfo_height()
            visible = bool(app.save_btn.winfo_viewable()) and bottom <= root.winfo_rooty() + root.winfo_height()
            info = (f"font={gui._font(root, 10)[0]} window={root.winfo_width()}x{root.winfo_height()} "
                    f"screen={root.winfo_screenwidth()}x{root.winfo_screenheight()} "
                    f"scaling={float(root.tk.call('tk', 'scaling')):.2f}")
        finally:
            root.destroy()
    if not visible:
        raise RuntimeError(f"設定の保存ボタンが画面に入っていません: {info}")
    return info


def run(out: Path, channel: str | None = "msedge") -> int:
    results: list[str] = []
    ok = True

    def check(name: str, fn) -> None:
        nonlocal ok
        try:
            results.append(f"OK   {name}: {fn()}")
        except Exception:
            ok = False
            results.append(f"FAIL {name}:\n{traceback.format_exc()}")

    check("import", _imports)
    check("tkinter", _tk)
    check("gui", _gui)

    # 画面と同じく、別スレッドで print を横取りした状態で Edge を動かす
    captured = io.StringIO()

    def worker():
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            check(f"browser({channel})", lambda: _browser_and_pdf(channel))

    t = threading.Thread(target=worker)
    t.start()
    t.join(180)
    if t.is_alive():
        ok = False
        results.append("FAIL browser: 180 秒以内に終わりませんでした")

    results.append("RESULT " + ("OK" if ok else "FAIL"))
    out.write_text("\n".join(results) + "\n", encoding="utf-8")
    return 0 if ok else 1
