import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from kaigo.config import Application
from kaigo.form import build_fields
from kaigo.receipts import Receipt, find_receipts
from kaigo.ui import month_choices, parse_amount, parse_date

APP = Application(
    care_name="介護　花子", care_name_kana="ｶｲｺﾞ　ﾊﾅｺ", relation="（義）祖父母", care_level="要介護5",
    cert_start="20250129", cert_end="20280131", bank_code="0009", bank_name="ﾃｽﾄｷﾞﾝｺｳ",
    branch_code="111", branch_name="ﾃｽﾄｼﾃﾝ", account_type="普通", account_number="1234567",
    account_holder="ﾃｽﾄﾀﾛｳ", url="",
)


def _receipts():
    return [
        Receipt("homecare", Path("領収書ホームケア_202610.pdf"), "20261002", 9710),
        Receipt("magokoro", Path("領収書まごころ_202610.pdf"), "20261001", 8426),
    ]


def test_build_fields_slots_and_total():
    fields = {f.label: f.value for f in build_fields(APP, _receipts())}
    assert fields["①メニューNo."] == "10640022"
    assert fields["①領収書発行年月日"] == "20261002"
    assert fields["②メニューNo."] == "10640395"
    assert fields["②領収書発行年月日"] == "20261001"
    assert fields["ご申請合計金額"] == "18136"
    assert "③メニューNo." not in fields


def test_build_fields_rejects_missing_values():
    r = _receipts()
    r[0].amount = None
    with pytest.raises(ValueError):
        build_fields(APP, r)


def test_month_choices_include_current_month_and_cross_year():
    assert month_choices(date(2026, 10, 7))[:3] == ["202610", "202609", "202608"]
    assert month_choices(date(2027, 1, 15))[:2] == ["202701", "202612"]


def test_parse_inputs():
    assert parse_date("20261002") == "20261002"
    assert parse_date("2026/10/2") == "20261002"
    assert parse_date("2026年10月2日") == "20261002"
    assert parse_date("20261332") is None
    assert parse_amount("9,710円") == 9710
    assert parse_amount("abc") is None


def test_find_receipts_naming_rules(tmp_path):
    for name in ["領収書まごころ_202610_2.pdf", "領収書まごころ_202610_1.pdf", "領収書ホームケア_202610 .pdf",
                 "領収書ホームケア_202609.pdf", "メモ.txt"]:
        (tmp_path / name).write_bytes(b"not a pdf")
    found = find_receipts(tmp_path, "202610")
    assert [r.path.name for r in found] == [
        "領収書ホームケア_202610 .pdf", "領収書まごころ_202610_1.pdf", "領収書まごころ_202610_2.pdf",
    ]
    assert all(r.date is None and r.note for r in found)


SAMPLE_DIR = os.environ.get("KAIGO_SAMPLE_DIR")


@pytest.mark.skipif(not SAMPLE_DIR, reason="実サンプル PDF のフォルダ（KAIGO_SAMPLE_DIR）未指定")
def test_find_receipts_real_samples(tmp_path):
    shutil.copy(Path(SAMPLE_DIR) / "magokoro.pdf", tmp_path / "領収書まごころ_202609.pdf")
    (r,) = find_receipts(tmp_path, "202609")
    assert (r.date, r.amount) == ("20260901", 8426)
