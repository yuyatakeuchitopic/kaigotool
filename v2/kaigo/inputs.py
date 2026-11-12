"""画面入力値の変換・チェック。"""

from __future__ import annotations

import re
from datetime import date, datetime

YM_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def month_choices(today: date, n_past: int = 12) -> list[str]:
    """当月から過去 n_past か月分の YYYYMM（新しい順）。毎回今日の日付から計算する。"""
    y, m = today.year, today.month
    out = []
    for _ in range(n_past + 1):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def parse_date(s: str) -> str | None:
    """「20260902」「2026/9/2」「2026-09-02」「2026年9月2日」→ 20260902。不正なら None。"""
    m = re.fullmatch(r"(\d{4})[/\-.年]?(\d{1,2})[/\-.月]?(\d{1,2})日?", s.strip())
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%Y%m%d")
    except ValueError:
        return None


def parse_amount(s: str) -> int | None:
    s = re.sub(r"[,，円¥￥\s]", "", s)
    return int(s) if s.isdigit() else None
