"""対象業者の定義（メール件名・保存ファイル名）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vendor:
    key: str
    label: str
    subject: str  # 件名に含まれる文字列（取得後の絞り込みに使用）
    search_phrase: str  # Gmail 検索に使う件名の一部
    file_prefix: str


VENDORS: dict[str, Vendor] = {
    "homecare": Vendor(
        key="homecare",
        label="フランスベッド・ホームケア全科",
        subject="ご注文商品発送及びお買上明細書URLのご連絡【フランスベッド ホームケア全科オンライン】",
        search_phrase="お買上明細書URLのご連絡",
        file_prefix="領収書ホームケア",
    ),
    "magokoro": Vendor(
        key="magokoro",
        label="まごころサポート",
        subject="【まごころサポート for ベネフィット・ステーション】ご注文ありがとうございました",
        search_phrase="まごころサポート for ベネフィット・ステーション",
        file_prefix="領収書まごころ",
    ),
}
