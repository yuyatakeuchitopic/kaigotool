"""メール本文から URL・注文番号を取り出す。"""

from __future__ import annotations

import re
import unicodedata

URL_RE = re.compile(r"https?://[^\s<>\"'「」（）()]+")


def normalize(text: str) -> str:
    """全角英数・康熙部首（PDF 由来の「⽇」等）を通常の文字にそろえる。"""
    return unicodedata.normalize("NFKC", text)


def url_after(texts: list[str], label: str, window: int = 600) -> str | None:
    """label の直後（window 文字以内）に現れる最初の URL を返す。"""
    label = normalize(label)
    for text in texts:
        t = normalize(text)
        start = 0
        while (idx := t.find(label, start)) != -1:
            m = URL_RE.search(t, idx + len(label), idx + len(label) + window)
            if m:
                return m.group(0)
            start = idx + len(label)
    return None


ORDER_NO_NEAR_LABEL = re.compile(r"注文番号[^P\n]{0,20}\n?[^P\n]{0,20}(P\d{6,})")
ORDER_NO = re.compile(r"(?<![A-Za-z0-9])(P\d{10,})(?!\d)")


def magokoro_order_number(texts: list[str]) -> str | None:
    """まごころサポートの注文番号（P から始まる数字列）を返す。"""
    for text in texts:
        t = normalize(text)
        m = ORDER_NO_NEAR_LABEL.search(t) or ORDER_NO.search(t)
        if m:
            return m.group(1)
    return None
