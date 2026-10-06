"""config.toml の読み込み。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RECEIPT_ROOT = r"C:\Users\you50\OneDrive\Documents\介護用品領収書"


@dataclass
class Config:
    receipt_root: Path
    gmail_address: str
    gmail_app_password: str
    browser_channel: str | None


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"設定ファイル {path} がありません。config.example.toml をコピーして作成してください。"
        )
    with path.open("rb") as f:
        data = tomllib.load(f)

    gmail = data.get("gmail", {})
    address = gmail.get("address", "").strip()
    password = gmail.get("app_password", "").replace(" ", "")
    if not address or not password:
        raise ValueError("config.toml の [gmail] address / app_password を設定してください。")

    return Config(
        receipt_root=Path(data.get("paths", {}).get("receipt_root", DEFAULT_RECEIPT_ROOT)),
        gmail_address=address,
        gmail_app_password=password,
        browser_channel=data.get("browser", {}).get("channel") or None,
    )
