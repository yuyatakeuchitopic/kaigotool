"""申請フォームに添付するファイルの選定。"""

from __future__ import annotations

from pathlib import Path

from .vendors import VENDORS

MAX_FILES = 5  # 申請サイトの上限: 1 項目あたり 5 ファイル
MAX_BYTES = 5 * 1024 * 1024  # 1 ファイル 5MB


def folder_pdfs(folder: Path) -> list[Path]:
    """フォルダ直下の PDF。領収書（ホームケア → まごころ）を先に、その他は名前順。"""
    if not folder.is_dir():
        return []
    pdfs = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".pdf")
    order = [v.file_prefix for v in VENDORS.values()]

    def key(f: Path):
        rank = next((i for i, p in enumerate(order) if f.name.startswith(p + "_")), len(order))
        return (rank, f.name)

    return sorted(pdfs, key=key)


def pick(files: list[Path]) -> tuple[list[Path], list[str]]:
    """サイトの制限（5MB / 5 ファイル）に合うものだけ返す。外したものは理由を返す。"""
    ok, notes = [], []
    for f in files:
        if f.stat().st_size > MAX_BYTES:
            notes.append(f"{f.name}: 5MB を超えるため添付しません")
        elif len(ok) >= MAX_FILES:
            notes.append(f"{f.name}: 1 項目 {MAX_FILES} ファイルまでのため添付しません")
        else:
            ok.append(f)
    return ok, notes
