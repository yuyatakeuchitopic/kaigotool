"""config.toml の読み込み。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_RECEIPT_ROOT = r"C:\Users\you50\OneDrive\Documents\介護用品領収書"
DEFAULT_APPLY_URL = (
    "https://life.bs.benefit-one.inc/menus/catExl=null/catLrg=110/catMid=202/catSml=301"
    "/menuNo=10640263/plans/planId=0010875118"
)


class ConfigError(Exception):
    pass


@dataclass
class Application:
    """Step2 の申請フォームに入力する固定値。"""

    care_name: str  # 介護対象者 氏名
    care_name_kana: str  # ｶｲｺﾞﾀｲｼｮｳｼｬ ｼﾒｲ
    relation: str  # 会員様との関係（プルダウン）
    care_level: str  # 要支援・要介護 度（プルダウン）
    cert_start: str  # 要介護認定の認定年月日（開始）YYYYMMDD
    cert_end: str  # 要介護認定の有効期限（終了）YYYYMMDD
    bank_code: str
    bank_name: str
    branch_code: str
    branch_name: str
    account_type: str  # 口座の種類（プルダウン）
    account_number: str
    account_holder: str  # ｺｳｻﾞﾒｲｷﾞﾆﾝ
    url: str = DEFAULT_APPLY_URL


@dataclass
class Config:
    receipt_root: Path
    gmail_address: str
    gmail_app_password: str
    browser_channel: str | None
    application: Application | None

    def require_gmail(self) -> None:
        if not self.gmail_address or not self.gmail_app_password:
            raise ConfigError("config.toml の [gmail] address / app_password を設定してください。")

    def require_application(self) -> Application:
        if self.application is None:
            raise ConfigError("config.toml に [application] がありません。config.example.toml を参考に追加してください。")
        return self.application


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(
            f"設定ファイル {path} がありません。\n"
            f"同じフォルダの config.example.toml をコピーして config.toml という名前で保存し、値を記入してください。"
        )
    with path.open("rb") as f:
        data = tomllib.load(f)

    gmail = data.get("gmail", {})
    return Config(
        receipt_root=Path(data.get("paths", {}).get("receipt_root", DEFAULT_RECEIPT_ROOT)),
        gmail_address=gmail.get("address", "").strip(),
        gmail_app_password=gmail.get("app_password", "").replace(" ", ""),
        browser_channel=data.get("browser", {}).get("channel") or None,
        application=_load_application(data.get("application")),
    )


def _load_application(raw: dict | None) -> Application | None:
    if raw is None:
        return None
    names = {f.name for f in fields(Application)}
    required = {f.name for f in fields(Application) if f.name != "url"}
    missing = sorted(n for n in required if not str(raw.get(n, "")).strip())
    if missing:
        raise ConfigError(f"config.toml の [application] に未記入の項目があります: {', '.join(missing)}")
    return Application(**{k: str(v).strip() for k, v in raw.items() if k in names})
