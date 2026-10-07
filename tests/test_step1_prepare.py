import os
import time

from kaigo.step1 import other_pdfs, prepare


def _touch(path, mtime=None):
    path.write_bytes(b"%PDF-1.4 dummy")
    if mtime:
        os.utime(path, (mtime, mtime))


def test_existing_files_end_processing(tmp_path):
    _touch(tmp_path / "領収書ホームケア_202610.pdf")
    _touch(tmp_path / "領収書まごころ_202610 .pdf")  # 拡張子前の空白も可
    results, need = prepare(tmp_path, "202610", ["homecare", "magokoro"])
    assert need == []
    assert [(r.vendor, r.file, r.status) for r in results] == [
        ("homecare", "領収書ホームケア_202610.pdf", "skipped"),
        ("magokoro", "領収書まごころ_202610 .pdf", "skipped"),
    ]


def test_other_pdf_is_renamed_to_magokoro(tmp_path):
    _touch(tmp_path / "領収書ホームケア_202610.pdf")
    _touch(tmp_path / "REC-7936-20261001.pdf")
    (tmp_path / "memo.txt").write_text("x")
    results, need = prepare(tmp_path, "202610", ["homecare", "magokoro"])
    assert need == []
    assert (tmp_path / "領収書まごころ_202610.pdf").exists()
    assert not (tmp_path / "REC-7936-20261001.pdf").exists()
    assert results[-1].status == "renamed"


def test_multiple_other_pdfs_get_numbered_oldest_first(tmp_path):
    now = time.time()
    _touch(tmp_path / "b.pdf", now - 100)
    _touch(tmp_path / "a.PDF", now)
    prepare(tmp_path, "202610", ["magokoro"])
    assert sorted(f.name for f in tmp_path.iterdir()) == ["領収書まごころ_202610_1.pdf", "領収書まごころ_202610_2.pdf"]
    assert other_pdfs(tmp_path) == []


def test_nothing_in_folder_needs_mail(tmp_path):
    results, need = prepare(tmp_path, "202610", ["homecare", "magokoro"])
    assert results == [] and need == ["homecare", "magokoro"]


def test_homecare_only_does_not_rename_other_pdfs(tmp_path):
    _touch(tmp_path / "REC.pdf")
    results, need = prepare(tmp_path, "202610", ["homecare"])
    assert need == ["homecare"] and (tmp_path / "REC.pdf").exists()


def test_overwrite_ignores_existing_and_does_not_rename(tmp_path):
    _touch(tmp_path / "領収書まごころ_202610.pdf")
    _touch(tmp_path / "REC.pdf")
    results, need = prepare(tmp_path, "202610", ["magokoro"], overwrite=True)
    assert results == [] and need == ["magokoro"] and (tmp_path / "REC.pdf").exists()


def test_run_without_gmail_when_folder_already_complete(tmp_path, capsys):
    from kaigo.settings import Settings
    from kaigo.step1 import run

    folder = tmp_path / "202610"
    folder.mkdir()
    _touch(folder / "領収書ホームケア_202610.pdf")
    _touch(folder / "manual-download.pdf")
    assert run(Settings(receipt_root=str(tmp_path)), "202610", ["homecare", "magokoro"]) == 0
    out = capsys.readouterr().out
    assert "既存のフォルダを使います" in out and "Gmail を検索" not in out
    assert (folder / "領収書まごころ_202610.pdf").exists()


def test_run_reports_missing_gmail_only_when_needed(tmp_path, capsys):
    from kaigo.settings import Settings
    from kaigo.step1 import run

    assert run(Settings(receipt_root=str(tmp_path)), "202610", ["magokoro"]) == 1
    assert "Gmail アドレスとアプリ パスワードを入力してください" in capsys.readouterr().out
    assert (tmp_path / "202610").is_dir()
