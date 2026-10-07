"""領収書の内容（日付・金額）を読み取る。Step2 の申請入力で使う。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .extract import normalize


@dataclass
class ReceiptInfo:
    date: str | None  # YYYYMMDD
    amount: int | None  # 円


def _ymd(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}{int(m):02d}{int(d):02d}"


def _yen(s: str) -> int:
    return int(s.replace(",", ""))


def _spaced(word: str) -> str:
    """「ご 注 文 日」のように文字間に空白が入っても一致する正規表現にする。"""
    return r"\s*".join(map(re.escape, word))


HOMECARE_DATE = re.compile(_spaced("ご注文日") + r"\s*:?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 「合計金額」行の最初の金額 = 「小計(税込)」列
HOMECARE_AMOUNT = re.compile(_spaced("合計金額") + r"\s*:?\s*[¥\\]?\s*([\d,]+)\s*円?")

MAGOKORO_DATE = re.compile(_spaced("発行日") + r"\s*:?\s*(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})")
MAGOKORO_AMOUNT = re.compile(_spaced("総合計") + r"\s*:?\s*[¥\\]?\s*([\d,]+)")


def parse_homecare(text: str) -> ReceiptInfo:
    """フランスベッド ホームケア全科「納品書 兼 お買上明細書」。"""
    t = normalize(text)
    d = HOMECARE_DATE.search(t)
    a = HOMECARE_AMOUNT.search(t)
    return ReceiptInfo(date=_ymd(*d.groups()) if d else None, amount=_yen(a.group(1)) if a else None)


def parse_magokoro(text: str) -> ReceiptInfo:
    """まごころサポート「領収書・納品書」。"""
    t = normalize(text)
    d = MAGOKORO_DATE.search(t)
    a = MAGOKORO_AMOUNT.search(t)
    return ReceiptInfo(date=_ymd(*d.groups()) if d else None, amount=_yen(a.group(1)) if a else None)


def pdf_text(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@dataclass
class Receipt:
    vendor: str  # VENDORS のキー
    path: Path
    date: str | None  # YYYYMMDD
    amount: int | None
    note: str = ""  # 読み取れなかった理由など


def _receipt_file_re(prefix: str, ym: str) -> re.Pattern:
    # 「領収書まごころ_202609 .pdf」のように拡張子前に空白があっても拾う
    return re.compile(rf"^{re.escape(prefix)}_{ym}(?:_(\d+))?\s*\.pdf$", re.IGNORECASE)


def find_receipts(folder: Path, ym: str) -> list[Receipt]:
    """YYYYMM フォルダから命名規則どおりの領収書 PDF を探して読み取る。

    並び順は ホームケア → まごころ、同じ業者は連番順。
    """
    from .vendors import VENDORS

    parsers = {"homecare": parse_homecare, "magokoro": parse_magokoro}
    files = sorted(folder.iterdir()) if folder.is_dir() else []
    out: list[Receipt] = []
    for key, vendor in VENDORS.items():
        pat = _receipt_file_re(vendor.file_prefix, ym)
        hits = [(int(m.group(1) or 0), f) for f in files if (m := pat.match(f.name))]
        for _, f in sorted(hits):
            out.append(_read_receipt(key, f, parsers[key]))
    return out


def _read_receipt(key: str, path: Path, parser) -> Receipt:
    try:
        text = pdf_text(path)
    except Exception as e:
        return Receipt(key, path, None, None, f"PDF を読めません: {e}")
    if not text.strip():
        return Receipt(key, path, None, None, "文字情報のない（画像の）PDF です。手入力してください")
    info = parser(text)
    note = "" if info.date and info.amount is not None else "一部読み取れませんでした。手入力してください"
    return Receipt(key, path, info.date, info.amount, note)
