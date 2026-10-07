"""画面で入力した設定の保存・読み込み。

保存先は %LOCALAPPDATA%\\kaigotool\\settings.json（PC 内のみ。GitHub には上がらない）。
「設定を保存」した値が次回起動時の既定値になる。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_RECEIPT_ROOT = r"C:\Users\you50\OneDrive\Documents\介護用品領収書"
DEFAULT_APPLY_URL = (
    "https://life.bs.benefit-one.inc/menus/catExl=null/catLrg=110/catMid=202/catSml=301"
    "/menuNo=10640263/plans/planId=0010875118"
)


@dataclass
class Application:
    """Step2 の申請フォームに入力する申請者情報。"""

    care_name: str = ""
    care_name_kana: str = ""
    relation: str = ""
    care_level: str = ""
    cert_start: str = ""
    cert_end: str = ""
    bank_code: str = ""
    bank_name: str = ""
    branch_code: str = ""
    branch_name: str = ""
    account_type: str = "普通"
    account_number: str = ""
    account_holder: str = ""


# 画面に表示する項目名（Application のフィールド順）
APPLICATION_LABELS = {
    "care_name": "介護対象者 氏名",
    "care_name_kana": "ｶｲｺﾞﾀｲｼｮｳｼｬ ｼﾒｲ",
    "relation": "会員様との関係",
    "care_level": "要支援・要介護 度",
    "cert_start": "認定年月日（開始）",
    "cert_end": "有効期限（終了）",
    "bank_code": "金融機関コード",
    "bank_name": "金融機関名",
    "branch_code": "支店コード",
    "branch_name": "支店名",
    "account_type": "口座の種類",
    "account_number": "口座番号",
    "account_holder": "ｺｳｻﾞﾒｲｷﾞﾆﾝ",
}


@dataclass
class Settings:
    receipt_root: str = DEFAULT_RECEIPT_ROOT
    gmail_address: str = ""
    gmail_app_password: str = ""
    magokoro_phone: str = ""  # まごころ納品書ページのログインに使う電話番号
    browser_channel: str = "msedge"
    apply_url: str = DEFAULT_APPLY_URL
    attachments_dir: str = DEFAULT_RECEIPT_ROOT + "\\毎回添付物"  # 介護保険証の写し等（毎回添付）
    step2_mode: str = "pdf"  # pdf: PDF から読み取り / manual: 画面の入力内容のみ
    application: Application = field(default_factory=Application)


def settings_path() -> Path:
    if os.environ.get("KAIGO_SETTINGS"):
        return Path(os.environ["KAIGO_SETTINGS"])
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "kaigotool" / "settings.json"


def _pick(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: str(v) for k, v in data.items() if k in names and v is not None}


def from_dict(data: dict) -> Settings:
    top = _pick(Settings, {k: v for k, v in data.items() if k != "application"})
    return Settings(**top, application=Application(**_pick(Application, data.get("application") or {})))


def load_settings(path: Path | None = None, legacy_toml: Path | None = None) -> Settings:
    """保存済みの設定を読む。無ければ旧形式の config.toml、それも無ければ初期値。"""
    path = path or settings_path()
    if path.exists():
        try:
            return from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            pass  # 壊れていたら初期値で起動（保存し直せば直る）
    if legacy_toml and legacy_toml.exists():
        return _from_legacy_toml(legacy_toml)
    return Settings()


def save_settings(s: Settings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _from_legacy_toml(path: Path) -> Settings:
    import tomllib

    with path.open("rb") as f:
        d = tomllib.load(f)
    app = dict(d.get("application", {}))
    return from_dict({
        "receipt_root": d.get("paths", {}).get("receipt_root", DEFAULT_RECEIPT_ROOT),
        "gmail_address": d.get("gmail", {}).get("address", ""),
        "gmail_app_password": str(d.get("gmail", {}).get("app_password", "")).replace(" ", ""),
        "browser_channel": d.get("browser", {}).get("channel", "msedge"),
        "apply_url": app.pop("url", DEFAULT_APPLY_URL),
        "application": app,
    })
