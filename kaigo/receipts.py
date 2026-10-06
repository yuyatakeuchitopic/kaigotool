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
