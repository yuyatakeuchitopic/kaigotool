"""起動時の依存ライブラリ確認と、実行ファイル（exe）版の判定。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REQUIRED = {"playwright": "playwright", "pdfplumber": "pdfplumber"}


def is_frozen() -> bool:
    """PyInstaller で作った exe として動いているか（Python 不要版）。"""
    return bool(getattr(sys, "frozen", False))


# ツールの置き場所（exe 版は exe のあるフォルダ、Python 版は app.py のあるフォルダ）
ROOT = Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent.parent


def missing_dependencies() -> list[str]:
    if is_frozen():
        return []  # exe には必要なものが同梱されている
    return [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]


def install_command() -> str:
    return (
        "start.bat をダブルクリックして起動してください（初回にライブラリを自動で入れます）。\n"
        f"手動の場合: & \"{sys.executable}\" -m pip install -r \"{ROOT / 'requirements.txt'}\""
    )
