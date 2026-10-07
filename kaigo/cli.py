"""起動時の依存ライブラリ確認。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REQUIRED = {"playwright": "playwright", "pdfplumber": "pdfplumber"}
ROOT = Path(__file__).resolve().parent.parent


def missing_dependencies() -> list[str]:
    return [pkg for mod, pkg in REQUIRED.items() if importlib.util.find_spec(mod) is None]


def install_command() -> str:
    return f"start.bat をダブルクリックして起動してください（初回にライブラリを自動で入れます）。\n手動の場合: & \"{sys.executable}\" -m pip install -r \"{ROOT / 'requirements.txt'}\""
