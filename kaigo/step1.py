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
from .receipts import ReceiptInfo, parse_homecare, parse_magokoro, pdf_text, receipt_files
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
    status: str = "ok"  # ok / skipped（既存）/ renamed（フォルダ内の PDF をリネーム）/ error
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
    magokoro_phone: str = "",
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
                    if not magokoro_phone:
                        raise RuntimeError("まごころ用の電話番号が未入力です（Step1 画面で入力してください）")
                    download_magokoro_receipt(browser_factory(None), url, order_no, magokoro_phone, dest)
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


def other_pdfs(folder: Path) -> list[Path]:
    """領収書の命名規則に当てはまらない PDF（手動ダウンロードしたもの等）を古い順に返す。"""
    prefixes = tuple(f"{v.file_prefix}_" for v in VENDORS.values())
    pdfs = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"
            and not f.name.startswith(prefixes)]
    return sorted(pdfs, key=lambda f: (f.stat().st_mtime, f.name))


def prepare(folder: Path, ym: str, vendor_keys: list[str], overwrite: bool = False) -> tuple[list[Result], list[str]]:
    """フォルダ内の既存ファイルで済む業者を処理し、(結果, メール取得が必要な業者) を返す。

    - 命名規則どおりのファイルが既にあれば、その業者は終了（取り直さない）
    - まごころ: 無ければ、フォルダ内のそれ以外の PDF を「領収書まごころ_YYYYMM.pdf」にリネーム
    """
    results: list[Result] = []
    need_mail: list[str] = []
    for key in vendor_keys:
        vendor = VENDORS[key]
        existing = receipt_files(folder, vendor.file_prefix, ym)
        if existing and not overwrite:
            for f in existing:
                print(f"[{vendor.label}] 既にあるため終了: {f.name}")
                results.append(_existing_result(key, f, "skipped"))
            continue
        if key == "magokoro" and not overwrite and (others := other_pdfs(folder)):
            for src, name in zip(others, file_names(vendor, ym, len(others))):
                dest = folder / name
                src.rename(dest)
                print(f"[{vendor.label}] フォルダ内の PDF をリネーム: {src.name} → {name}")
                results.append(_existing_result(key, dest, "renamed"))
            continue
        need_mail.append(key)
    return results, need_mail


def _existing_result(key: str, path: Path, status: str) -> Result:
    info = _parse_existing(key, path)
    return Result(vendor=key, file=path.name, mail_date="", subject="", receipt_date=info.date,
                  amount=info.amount, status=status)


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
        mark = {"ok": "○", "skipped": "－(既存)", "renamed": "○(リネーム)", "error": "×"}[r.status]
        print(f"{mark} {r.file}  日付:{r.receipt_date or '不明'}  {amount}" + (f"  {r.error}" if r.error else ""))
    total = sum(r.amount or 0 for r in results if r.status != "error")
    print(f"合計: {total:,}円")


def run(cfg: Settings, ym: str, vendor_keys: list[str], overwrite: bool = False, show_browser: bool = False) -> int:
    month_range(ym)  # 形式チェック
    folder = Path(cfg.receipt_root) / ym
    if folder.is_dir():
        print(f"既存のフォルダを使います: {folder}")
    else:
        folder.mkdir(parents=True)
        print(f"フォルダを作成しました: {folder}")

    results, need_mail = prepare(folder, ym, vendor_keys, overwrite)
    if need_mail:
        if not cfg.gmail_address or not cfg.gmail_app_password:
            print("× Gmail アドレスとアプリ パスワードを入力してください（メールからの取得に必要です）")
            return 1
        print("Gmail を検索しています...")
        mails = fetch_mails(cfg, ym, need_mail)
        results += _download(cfg, folder, ym, mails, overwrite, show_browser)

    summary = write_summary(folder, ym, results)
    print_summary(results)
    print(f"\n読み取り結果: {summary}")
    return 1 if any(r.status == "error" for r in results) else 0


def _download(cfg: Settings, folder: Path, ym: str, mails, overwrite: bool, show_browser: bool) -> list[Result]:
    from playwright.sync_api import sync_playwright

    with ExitStack() as stack:
        pw = None
        contexts: dict[bool, object] = {}

        def browser_factory(headless: bool | None):
            # PDF 印刷はヘッドレス必須。None はダウンロード用で、show_browser 時のみ画面表示
            nonlocal pw
            headless = (not show_browser) if headless is None else headless
            if headless not in contexts:
                if pw is None:
                    pw = stack.enter_context(sync_playwright())
                browser = pw.chromium.launch(channel=cfg.browser_channel or None, headless=headless)
                stack.callback(browser.close)
                contexts[headless] = browser.new_context(accept_downloads=True, locale="ja-JP")
            return contexts[headless]

        return process(folder, ym, mails, browser_factory, overwrite=overwrite, magokoro_phone=cfg.magokoro_phone)
