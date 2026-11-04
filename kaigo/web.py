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


REISSUE_TIMEOUT_MS = 10 * 60 * 1000  # 再発行で「確認」を押してもらうまで待つ時間
ISSUE_BUTTON_NAME = re.compile(r"^\s*発\s*行\s*$")  # プレビュー画面の「発 行」
CONFIRM_ISSUE_NAME = re.compile(r"^\s*発\s*行\s*す\s*る\s*$")  # 確認画面の「発行する」


def download_magokoro_receipt(
    context: BrowserContext,
    url: str,
    order_no: str,
    phone: str,
    dest: Path,
    ask_reason=None,
    timeout_ms: int = 30_000,
) -> None:
    """ラク帳票で 注文番号・電話番号 を入力してログインし、領収書・納品書の PDF を dest に保存する。

    - 初回: プレビューの「発 行」→ 確認画面の「発行する」でダウンロード
    - 発行済み: 再申請の画面になる。ask_reason() で理由を聞いて入力し、注意事項にチェックを入れ、
      「確認」はユーザーが押す（ダウンロードされるまで待つ）
    """
    page = context.new_page()
    downloads: list[Download] = []
    popups: list[Page] = []
    pdf_responses = []

    def on_download(d: Download) -> None:
        downloads.append(d)

    def on_page(p: Page) -> None:
        # 「ポップアップブロックの解除」が必要なサイト: ファイルは新しいウィンドウ側で届く
        popups.append(p)
        p.on("download", on_download)

    def on_response(r) -> None:
        if "application/pdf" in (r.headers.get("content-type") or ""):
            pdf_responses.append(r)

    def reset_received() -> int:
        """これまでに届いたもの（プレビュー用など）は使わない。"""
        downloads.clear()
        pdf_responses.clear()
        return len(popups)

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
        print("  「領収書・納品書を発行する」を押しました")

        kind, target = _wait_preview_or_reissue(context, page, popups, timeout_ms)
        if kind == "preview":
            known = reset_received()
            target.click()
            print(f"  プレビュー画面の「発行」を押しました: {target.page.url}")

            def received():
                return downloads or pdf_responses or _pdf_popup(popups[known:])

            # 確認画面（「以下の内容で発行します。よろしいですか？」）の「発行する」を押す
            confirm_pressed = False
            deadline = time.monotonic() + timeout_ms / 1000
            while not received() and time.monotonic() < deadline:
                if not confirm_pressed:
                    btn = _visible_named(target.page, CONFIRM_ISSUE_NAME)
                    if btn is not None:
                        btn.click()
                        confirm_pressed = True
                        print("  確認画面の「発行する」を押しました")
                _pump(context)
            if not received():
                raise RuntimeError("「発行する」を押した後のファイルのダウンロードを検出できませんでした")
        else:
            print("  この領収書は発行済みのため、再発行（再申請）の手続きになります")
            _fill_reissue_form(target, ask_reason)
            known = reset_received()
            target.bring_to_front()
            print("  ★ ブラウザの「確認」ボタンを押してください（画面の指示に従ってダウンロードまで進めてください。"
                  "最大10分待ちます）")

            def received():
                return downloads or pdf_responses or _pdf_popup(popups[known:])

            deadline = time.monotonic() + REISSUE_TIMEOUT_MS / 1000
            while not received() and time.monotonic() < deadline:
                _pump(context)
            if not received():
                raise RuntimeError("再発行のファイルが10分以内にダウンロードされませんでした")

        _save_file(context, downloads, pdf_responses, popups[known:], dest)
        print(f"  保存しました: {dest.name}（{dest.stat().st_size:,} バイト）")
        if not dest.read_bytes()[:5] == b"%PDF-":
            dest.unlink()
            raise RuntimeError("ダウンロードしたファイルが PDF ではありませんでした")
    except Exception:
        try:
            page.screenshot(path=str(dest.with_suffix(".error.png")), full_page=True)
        except Exception:
            pass
        raise
    finally:
        context.remove_listener("page", on_page)
        context.remove_listener("response", on_response)
        for p in [*popups, page]:
            try:
                p.close()
            except Exception:
                pass


def _wait_preview_or_reissue(context, page: Page, popups: list[Page], timeout_ms: int):
    """プレビュー画面の「発 行」ボタン、または再申請の入力画面が出るまで待つ。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for p in [*reversed(popups), page]:
            if p.is_closed():
                continue
            if _is_reissue_page(p):
                p.bring_to_front()
                return "reissue", p
            btn = _visible_named(p, ISSUE_BUTTON_NAME)
            if btn is not None:
                p.bring_to_front()
                return "preview", btn
        _pump(context)
    raise RuntimeError("プレビュー画面の「発行」ボタンも再申請の画面も見つかりません")


def _is_reissue_page(p: Page) -> bool:
    return p.get_by_text(re.compile("再申請理由")).count() > 0 and p.locator("textarea").count() > 0


def _fill_reissue_form(p: Page, ask_reason) -> None:
    if ask_reason is None:
        raise RuntimeError("発行済みのため再発行が必要です（画面から実行してください）")
    reason = (ask_reason() or "").strip()
    if not reason:
        raise RuntimeError("再申請理由が入力されなかったため中止しました")
    find_visible(p, [p.locator("textarea")], 10_000, "再申請理由の入力欄").fill(reason)
    print(f"  再申請理由を入力しました: {reason}")
    cb = find_visible(
        p,
        [p.get_by_label(re.compile("注意事項を理解")), p.locator("input[type='checkbox']")],
        10_000,
        "「注意事項を理解し…」のチェック欄",
    )
    if not cb.is_checked():
        cb.check(force=True)
    print("  「注意事項を理解し、以前の納品書・領収書は破棄いたします。」にチェックを入れました")


def _visible_named(p: Page, name: re.Pattern) -> Locator | None:
    """名前が name に一致する、表示中のボタン（リンク・文字だけのボタンも含む）。"""
    if p.is_closed():
        return None
    for loc in (p.get_by_role("button", name=name), p.get_by_role("link", name=name), p.get_by_text(name)):
        try:
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible() and el.is_enabled():
                    return el
        except Exception:
            pass
    return None


def _pump(context) -> None:
    """少し待つ（待っている間にダウンロード等のイベントが処理される）。"""
    for p in context.pages:
        if not p.is_closed():
            p.wait_for_timeout(250)
            return
    raise RuntimeError("ブラウザが閉じられました")


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
