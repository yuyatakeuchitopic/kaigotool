"""起動スクリプト共通処理（依存ライブラリ確認・エラー表示）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REQUIRED = {"playwright": "playwright", "pdfplumber": "pdfplumber"}
ROOT = Path(__file__).resolve().parent.parent


def check_dependencies() -> bool:
    missing = [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return True
    req = ROOT / "requirements.txt"
    print(f"必要なライブラリが入っていません: {', '.join(missing)}")
    print("次のコマンドを（このターミナルで）実行してから、もう一度起動してください:\n")
    print(f'  & "{sys.executable}" -m pip install -r "{req}"\n')
    return False
