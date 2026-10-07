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
    context: BrowserContext, url: str, order_no: str, dest: Path, timeout_ms: int = 30_000
) -> None:
    """納品書ダウンロードページで注文番号を入力し、PDF をダウンロードして dest に保存する。"""
    page = context.new_page()
    downloads: list[Download] = []
    popups: list[Page] = []

    def on_download(d: Download) -> None:
        downloads.append(d)

    def on_page(p: Page) -> None:
        popups.append(p)

    page.on("download", on_download)
    page.on("dialog", lambda d: d.accept())  # JavaScript の確認ダイアログは OK
    context.on("page", on_page)
    try:
        page.goto(url, wait_until="domcontentloaded")
        find_visible(page, _order_inputs(page), timeout_ms, "注文番号の入力欄").fill(order_no)
        find_visible(page, buttons(page, ["発行する"]), timeout_ms, "「発行する」ボタン").click()

        # 「発行する」で直接ダウンロードされない場合は「確認」「発行」を押す
        if not _wait(page, lambda: downloads or _pdf_popup(popups), 5_000):
            find_visible(page, buttons(page, ["確認", "発行"]), timeout_ms, "「確認」/「発行」ボタン").click()
            if not _wait(page, lambda: downloads or _pdf_popup(popups), timeout_ms):
                raise RuntimeError("納品書ファイルのダウンロードを検出できませんでした")

        if downloads:
            downloads[0].save_as(dest)
        else:
            # ダウンロードではなく PDF が新しいタブで開いた場合
            resp = context.request.get(_pdf_popup(popups).url)
            dest.write_bytes(resp.body())
    except Exception:
        page.screenshot(path=str(dest.with_suffix(".error.png")), full_page=True)
        raise
    finally:
        context.remove_listener("page", on_page)
        for p in popups:
            p.close()
        page.close()


def _order_inputs(page: Page) -> list[Locator]:
    return [
        page.get_by_label(re.compile("注文番号")),
        page.get_by_placeholder(re.compile("注文番号|P\\d")),
        page.locator("input[name*='order' i], input[id*='order' i]"),
        page.locator("input[type='text'], input:not([type])"),
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
