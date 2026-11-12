from datetime import date
from pathlib import Path

from kaigo.form import Slot, build_fields
from kaigo.inputs import month_choices, parse_amount, parse_date
from kaigo.receipts import find_receipts
from kaigo.settings import Application, Settings, load_settings, save_settings


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    assert load_settings(path) == Settings()  # 初回は初期値
    s = Settings(gmail_address="a@example.com", step2_mode="manual",
                 application=Application(care_name="介護　花子", account_type="当座"))
    save_settings(s, path)
    assert load_settings(path) == s


def test_settings_broken_file_falls_back(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_settings(path) == Settings()


def test_settings_seeded_from_legacy_toml(tmp_path):
    toml = tmp_path / "config.toml"
    toml.write_text('[gmail]\naddress = "x@example.com"\napp_password = "ab cd"\n'
                    '[application]\ncare_name = "介護　花子"\nurl = "https://example.com/plan"\n', encoding="utf-8")
    s = load_settings(tmp_path / "none.json", legacy_toml=toml)
    assert (s.gmail_address, s.gmail_app_password, s.apply_url) == ("x@example.com", "abcd", "https://example.com/plan")
    assert s.application.care_name == "介護　花子"


def test_build_fields_compacts_slots_and_skips_blank():
    app = Application(care_name="介護　花子")
    fields = {f.label: f.value for f in build_fields(app, [Slot("", "", ""), Slot("10640395", "まごころ", "20261001")], "8426")}
    assert fields["①メニューNo."] == "10640395" and fields["①領収書発行年月日"] == "20261001"
    assert fields["ご申請合計金額"] == "8426"
    assert "②メニューNo." not in fields and "金融機関コード" not in fields
    assert fields["口座の種類"] == "普通"  # 初期値


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
    assert find_receipts(Path(tmp_path / "nofolder"), "202610") == []


def test_attachment_selection(tmp_path):
    from kaigo import attachments

    for name in ["メモ.pdf", "領収書まごころ_202610.pdf", "領収書ホームケア_202610.pdf", "a.txt"]:
        (tmp_path / name).write_bytes(b"%PDF")
    (tmp_path / "big.pdf").write_bytes(b"0" * (attachments.MAX_BYTES + 1))
    files = attachments.folder_pdfs(tmp_path)
    assert [f.name for f in files] == ["領収書ホームケア_202610.pdf", "領収書まごころ_202610.pdf", "big.pdf", "メモ.pdf"]
    ok, notes = attachments.pick(files)
    assert [f.name for f in ok] == ["領収書ホームケア_202610.pdf", "領収書まごころ_202610.pdf", "メモ.pdf"]
    assert len(notes) == 1 and "5MB" in notes[0]
    assert attachments.folder_pdfs(tmp_path / "none") == []
