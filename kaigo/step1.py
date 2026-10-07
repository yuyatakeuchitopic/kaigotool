"""Step1: Gmail から領収書を取得して YYYYMM フォルダに保存する。"""

from __future__ import annotations

import json
import re
import traceback
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .settings import Settings
from .extract import magokoro_order_number, normalize, url_after
from .mail import GmailImap, Mail
from .receipts import ReceiptInfo, parse_homecare, parse_magokoro, pdf_text
from .vendors import VENDORS, Vendor

JST = timezone(timedelta(hours=9))
SUMMARY_FILE = "receipts.json"


@dataclass
class Result:
    vendor: str
    file: str
    mail_date: str
    subject: str
    receipt_date: str | None = None  # YYYYMMDD
    amount: int | None = None
    status: str = "ok"  # ok / skipped / error
    error: str | None = None


def month_range(ym: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{6}", ym) or not 1 <= int(ym[4:]) <= 12:
        raise ValueError(f"対象年月は YYYYMM 形式で指定してください: {ym}")
    y, m = int(ym[:4]), int(ym[4:])
    start = datetime(y, m, 1, tzinfo=JST)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=JST)
    return start, end


def gmail_query(vendor: Vendor, ym: str) -> str:
    start, end = month_range(ym)
    return f'subject:"{vendor.search_phrase}" after:{int(start.timestamp())} before:{int(end.timestamp())}'


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", normalize(s))


def select_mails(vendor: Vendor, ym: str, mails: list[Mail]) -> list[Mail]:
    """件名・受信日時（日本時間）で絞り込み、古い順に並べる。"""
    start, end = month_range(ym)
    hits = [
        m for m in mails
        if _compact(vendor.subject) in _compact(m.subject) and start <= m.date.astimezone(JST) < end
    ]
    return sorted(hits, key=lambda m: m.date)


def file_names(vendor: Vendor, ym: str, count: int) -> list[str]:
    """1 通なら 領収書xx_YYYYMM.pdf、複数通なら _1, _2 ... の連番。"""
    if count == 1:
        return [f"{vendor.file_prefix}_{ym}.pdf"]
    return [f"{vendor.file_prefix}_{ym}_{i}.pdf" for i in range(1, count + 1)]


def fetch_mails(cfg: Settings, ym: str, vendor_keys: list[str]) -> dict[str, list[Mail]]:
    out: dict[str, list[Mail]] = {}
    with GmailImap(cfg.gmail_address, cfg.gmail_app_password) as gmail:
        for key in vendor_keys:
            vendor = VENDORS[key]
            mails = [gmail.fetch(uid) for uid in gmail.search(gmail_query(vendor, ym))]
            out[key] = select_mails(vendor, ym, mails)
    return out


def process(
    folder: Path,
    ym: str,
    mails_by_vendor: dict[str, list[Mail]],
    browser_factory,
    overwrite: bool = False,
) -> list[Result]:
    """メールごとに領収書を保存する。browser_factory(headless) は BrowserContext を返す。"""
    from .web import download_magokoro_receipt, save_homecare_receipt

    results: list[Result] = []
    for key, mails in mails_by_vendor.items():
        vendor = VENDORS[key]
        if not mails:
            print(f"[{vendor.label}] {ym} の対象メールはありません")
            continue
        for mail, name in zip(mails, file_names(vendor, ym, len(mails))):
            dest = folder / name
            r = Result(
                vendor=key, file=name, mail_date=mail.date.astimezone(JST).isoformat(), subject=mail.subject
            )
            print(f"[{vendor.label}] {mail.date.astimezone(JST):%Y-%m-%d %H:%M} のメール → {name}")
            try:
                if dest.exists() and not overwrite:
                    r.status = "skipped"
                    info = _parse_existing(key, dest)
                elif key == "homecare":
                    url = url_after(mail.bodies, "電子領収書URL")
                    if not url:
                        raise RuntimeError("メール本文に「電子領収書URL」が見つかりません")
                    info = save_homecare_receipt(browser_factory(True), url, dest)
                else:
                    order_no = magokoro_order_number(mail.bodies)
                    url = url_after(mail.bodies, "納品書ダウンロード用URL")
                    if not order_no or not url:
                        raise RuntimeError(f"注文番号({order_no}) または 納品書URL({url}) が見つかりません")
                    download_magokoro_receipt(browser_factory(None), url, order_no, dest)
                    info = parse_magokoro(pdf_text(dest))
                r.receipt_date, r.amount = info.date, info.amount
                if info.date is None or info.amount is None:
                    print("  ※ 日付/金額を読み取れませんでした（Step2 で手入力が必要）")
            except Exception as e:  # 1 件失敗しても残りは続ける
                r.status, r.error = "error", str(e)
                print(f"  × 失敗: {e}")
                traceback.print_exc()
            results.append(r)
    return results


def _parse_existing(key: str, path: Path) -> ReceiptInfo:
    try:
        text = pdf_text(path)
    except Exception:
        return ReceiptInfo(None, None)
    return parse_homecare(text) if key == "homecare" else parse_magokoro(text)


def write_summary(folder: Path, ym: str, results: list[Result]) -> Path:
    path = folder / SUMMARY_FILE
    data = {"month": ym, "receipts": [asdict(r) for r in results]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_summary(results: list[Result]) -> None:
    print("\n==== 結果 ====")
    for r in results:
        amount = f"{r.amount:,}円" if r.amount is not None else "金額不明"
        mark = {"ok": "○", "skipped": "－(既存)", "error": "×"}[r.status]
        print(f"{mark} {r.file}  日付:{r.receipt_date or '不明'}  {amount}" + (f"  {r.error}" if r.error else ""))
    total = sum(r.amount or 0 for r in results if r.status != "error")
    print(f"合計: {total:,}円")


def run(cfg: Settings, ym: str, vendor_keys: list[str], overwrite: bool = False, show_browser: bool = False) -> int:
    folder = Path(cfg.receipt_root) / ym
    folder.mkdir(parents=True, exist_ok=True)
    print(f"保存先: {folder}")

    print("Gmail を検索しています...")
    mails = fetch_mails(cfg, ym, vendor_keys)

    from playwright.sync_api import sync_playwright

    with ExitStack() as stack:
        pw = None
        contexts: dict[bool, object] = {}

        def browser_factory(headless: bool | None):
            # PDF 印刷はヘッドレス必須。None はダウンロード用で、--show-browser 時のみ画面表示
            nonlocal pw
            headless = (not show_browser) if headless is None else headless
            if headless not in contexts:
                if pw is None:
                    pw = stack.enter_context(sync_playwright())
                browser = pw.chromium.launch(channel=cfg.browser_channel or None, headless=headless)
                stack.callback(browser.close)
                contexts[headless] = browser.new_context(accept_downloads=True, locale="ja-JP")
            return contexts[headless]

        results = process(folder, ym, mails, browser_factory, overwrite=overwrite)

    summary = write_summary(folder, ym, results)
    print_summary(results)
    print(f"\n読み取り結果: {summary}")
    return 1 if any(r.status == "error" for r in results) else 0
