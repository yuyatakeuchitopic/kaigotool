"""ブラウザ操作（Playwright）。"""

from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Download, Locator, Page

from .receipts import ReceiptInfo, parse_homecare


def save_homecare_receipt(context: BrowserContext, url: str, dest: Path) -> ReceiptInfo:
    """電子領収書ページを開いて PDF 保存し、ページ本文から日付・金額を読む。

    page.pdf() はヘッドレス起動時のみ使える。
    """
    page = context.new_page()
    try:
        page.goto(url, wait_until="networkidle")
        text = page.inner_text("body")
        page.pdf(path=str(dest), format="A4", print_background=True)
        return parse_homecare(text)
    finally:
        page.close()


def download_magokoro_receipt(
    context: BrowserContext, url: str, order_no: str, phone: str, dest: Path, timeout_ms: int = 30_000
) -> None:
    """納品書ダウンロードページで 注文番号・電話番号 を入力してログインし、
    「領収書・納品書を発行する」で PDF をダウンロードして dest に保存する。"""
    page = context.new_page()
    downloads: list[Download] = []
    popups: list[Page] = []

    def on_download(d: Download) -> None:
        downloads.append(d)

    pdf_responses = []

    def on_page(p: Page) -> None:
        # 「ポップアップブロックの解除」が必要なサイト: ファイルは新しいウィンドウ側で届く
        popups.append(p)
        p.on("download", on_download)

    def on_response(r) -> None:
        if "application/pdf" in (r.headers.get("content-type") or ""):
            pdf_responses.append(r)

    page.on("download", on_download)
    page.on("dialog", lambda d: d.accept())  # JavaScript の確認ダイアログは OK
    context.on("page", on_page)
    context.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded")
        print(f"  納品書ページを開きました: {page.url}")
        find_visible(page, _order_inputs(page), timeout_ms, "注文番号の入力欄").fill(order_no)
        find_visible(page, _phone_inputs(page), timeout_ms, "電話番号の入力欄").fill(phone)
        find_visible(page, buttons(page, ["ログイン"]), timeout_ms, "「ログイン」ボタン").click()
        print("  ログインしました")
        find_visible(
            page, buttons(page, ["領収書・納品書を発行する"]), timeout_ms, "「領収書・納品書を発行する」ボタン"
        ).click()

        # プレビュー画面（同じタブまたは新しいウィンドウ）の「発 行」ボタンを押すと本物の PDF が届く。
        # プレビュー表示中に届くもの（プレビュー用の画像・PDF）は使わない
        print("  「領収書・納品書を発行する」を押しました")
        issue_btn = _find_issue_button(page, popups, timeout_ms)
        downloads.clear()
        pdf_responses.clear()
        known_popups = len(popups)
        issue_btn.click()
        print(f"  プレビュー画面の「発行」を押しました: {issue_btn.page.url}")

        def got_issued_file():
            return downloads or pdf_responses or _pdf_popup(popups[known_popups:])

        if not _wait(page, got_issued_file, timeout_ms):
            raise RuntimeError("「発行」を押した後のファイルのダウンロードを検出できませんでした")

        _save_file(context, downloads, pdf_responses, popups[known_popups:], dest)
        print(f"  保存しました: {dest.name}（{dest.stat().st_size:,} バイト）")
        if not dest.read_bytes()[:5] == b"%PDF-":
            dest.unlink()
            raise RuntimeError("ダウンロードしたファイルが PDF ではありませんでした")
    except Exception:
        page.screenshot(path=str(dest.with_suffix(".error.png")), full_page=True)
        raise
    finally:
        context.remove_listener("page", on_page)
        context.remove_listener("response", on_response)
        for p in popups:
            p.close()
        page.close()


def _save_file(context, downloads, pdf_responses, popups, dest: Path) -> None:
    if downloads:
        print(f"  ダウンロードを受信: {downloads[0].suggested_filename}（{downloads[0].url}）")
        downloads[0].save_as(dest)
        return
    for r in pdf_responses:  # PDF がタブ内に表示された場合
        try:
            dest.write_bytes(r.body())
            print(f"  画面に表示された PDF を受信: {r.url}")
            return
        except Exception:
            pass
    popup = _pdf_popup(popups)
    if popup is None:
        raise RuntimeError("領収書・納品書ファイルを取得できませんでした")
    dest.write_bytes(context.request.get(popup.url).body())


ISSUE_BUTTON_NAME = re.compile(r"^\s*発\s*行\s*$")  # 画面上は「発 行」


def _find_issue_button(page: Page, popups: list[Page], timeout_ms: int) -> Locator:
    """プレビュー画面の「発 行」ボタン。新しいウィンドウで開く場合もあるので全ページを探す。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for p in [*reversed(popups), page]:
            if p.is_closed():
                continue
            for loc in (p.get_by_role("button", name=ISSUE_BUTTON_NAME),
                        p.get_by_role("link", name=ISSUE_BUTTON_NAME)):
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible() and el.is_enabled():
                        p.bring_to_front()
                        return el
        page.wait_for_timeout(250)
    raise RuntimeError("プレビュー画面の「発行」ボタンが見つかりません")


def _order_inputs(page: Page) -> list[Locator]:
    return [
        page.get_by_label(re.compile("注文番号")),
        page.get_by_placeholder(re.compile("注文番号|P\\d")),
        page.locator("input[name*='order' i], input[id*='order' i]"),
        page.locator("input[type='text'], input:not([type])").first,
    ]


def _phone_inputs(page: Page) -> list[Locator]:
    return [
        page.get_by_label(re.compile("電話番号")),
        page.get_by_placeholder(re.compile("電話番号|0\\d{9}")),
        # 電話番号はパスワード扱い（伏せ字）の入力欄になっている
        page.locator("input[type='password'], input[type='tel'], input[name*='tel' i], input[id*='tel' i],"
                     " input[name*='phone' i]"),
        page.locator("input[type='text'], input:not([type])").nth(1),
    ]


def buttons(page: Page, names: list[str]) -> list[Locator]:
    out: list[Locator] = []
    for exact in (True, False):
        for name in names:
            out.append(page.get_by_role("button", name=name, exact=exact))
            out.append(page.get_by_role("link", name=name, exact=exact))
    return out


def find_visible(page: Page, candidates: list[Locator], timeout_ms: int, what: str) -> Locator:
    """候補のうち最初に見つかった表示中の要素を返す。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for loc in candidates:
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible() and el.is_enabled():
                    return el
        page.wait_for_timeout(250)
    raise RuntimeError(f"{what}が見つかりません: {page.url}")


def _wait(page: Page, cond, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if cond():
            return True
        page.wait_for_timeout(250)
    return bool(cond())


def _pdf_popup(popups: list[Page]) -> Page | None:
    for p in popups:
        if p.url.lower().split("?")[0].endswith(".pdf"):
            return p
    return None
