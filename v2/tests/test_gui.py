"""画面（tkinter）の動作確認。表示環境が無ければスキップ。"""

import os
import shutil
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from kaigo.gui import MODE_MANUAL, MODE_PDF, App  # noqa: E402
from kaigo.settings import load_settings  # noqa: E402

SAMPLE_DIR = os.environ.get("KAIGO_SAMPLE_DIR")


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("表示環境がありません")
    a = App(root, settings_file=tmp_path / "settings.json")
    a.root_var.set(str(tmp_path / "receipts"))
    yield a
    root.destroy()


def _fill_app(a: App):
    for k, v in {"care_name": "介護　花子", "cert_start": "20250129", "bank_code": "0009"}.items():
        a.app_vars[k].set(v)


def test_defaults_and_saved_values_become_next_defaults(app, tmp_path):
    # 初期状態: ①ホームケア ②まごころ のメニューが入っている
    assert app.slots[0]["no"].get() == "10640022"
    assert app.slots[1]["no"].get() == "10640395"
    _fill_app(app)
    app.mode.set(MODE_MANUAL)
    app.save()
    s = load_settings(tmp_path / "settings.json")
    assert s.application.care_name == "介護　花子" and s.step2_mode == MODE_MANUAL

    # 再起動すると保存した値が既定値になる
    root2 = tk.Toplevel(app.root)
    a2 = App(root2, settings_file=tmp_path / "settings.json")
    assert a2.app_vars["care_name"].get() == "介護　花子"
    assert a2.mode.get() == MODE_MANUAL


def test_manual_mode_uses_screen_values_only(app):
    _fill_app(app)
    app.mode.set(MODE_MANUAL)
    app._apply_mode()
    app.slots[1]["date"].set("2026/10/1")  # ②まごころだけ（①は日付なし → 使わない）
    app.total_var.set("8,426")
    fields = {f.label: f.value for f in app.step2_fields()}
    assert fields["①メニューNo."] == "10640395" and fields["①領収書発行年月日"] == "20261001"
    assert "②メニューNo." not in fields
    assert fields["ご申請合計金額"] == "8426"


def test_pdf_mode_auto_total(app):
    _fill_app(app)
    app.mode.set(MODE_PDF)
    app._apply_mode()
    app.slots[0]["date"].set("20261002")
    app.slots[0]["amount"].set("9710")
    app.slots[1]["date"].set("20261001")
    app.slots[1]["amount"].set("8,426")
    assert app.total_var.get() == "18136"
    fields = {f.label: f.value for f in app.step2_fields()}
    assert fields["ご申請合計金額"] == "18136"
    app.slots[1]["amount"].set("")
    with pytest.raises(ValueError):
        app.step2_fields()


def test_bad_date_is_rejected(app):
    app.slots[0]["date"].set("2026/13/40")
    with pytest.raises(ValueError):
        app.step2_fields()


@pytest.mark.skipif(not SAMPLE_DIR, reason="実サンプル PDF のフォルダ（KAIGO_SAMPLE_DIR）未指定")
def test_load_pdfs_from_folder(app, tmp_path):
    folder = tmp_path / "receipts" / "202609"
    folder.mkdir(parents=True)
    shutil.copy(Path(SAMPLE_DIR) / "magokoro.pdf", folder / "領収書まごころ_202609.pdf")
    shutil.copy(Path(SAMPLE_DIR) / "homecare_image.pdf", folder / "領収書ホームケア_202609.pdf")
    app.mode.set(MODE_PDF)
    app._apply_mode()
    app.month2.set("202609")
    app.load_pdfs()
    hc, mg = app.slots[0], app.slots[1]
    assert hc["no"].get() == "10640022" and hc["date"].get() == "" and "画像" in hc["note"].get()
    assert (mg["date"].get(), mg["amount"].get()) == ("20260901", "8426")
    assert app.total_var.get() == ""  # ホームケアの金額が未入力
    with pytest.raises(ValueError):  # 読み込んだ行が未入力のままなら申請に進めない
        app.step2_fields()
    hc["date"].set("20260902")
    hc["amount"].set("9710")
    assert app.total_var.get() == "18136"


def test_background_task_output_goes_to_log(app):
    done = []
    app._start("テスト", lambda: print("処理中です") or 0, done.append)
    assert str(app.run2_btn["state"]) == "disabled"
    for _ in range(50):
        app.root.update()
        if done:
            break
        app.root.after(50)
    assert done == [0] and not app.busy
    assert "処理中です" in app.log.get("1.0", "end")
    assert str(app.run2_btn["state"]) == "normal"


def test_attachments_from_month_folder_and_saved_dir(app, tmp_path):
    month = tmp_path / "receipts" / "202610"
    month.mkdir(parents=True)
    (month / "領収書まごころ_202610.pdf").write_bytes(b"%PDF")
    every = tmp_path / "毎回添付物"
    every.mkdir()
    (every / "保険証.pdf").write_bytes(b"%PDF")
    app.month2.set("202610")
    app.attach_dir_var.set(str(every))
    app.slots[1]["date"].set("20261001")
    app.slots[1]["amount"].set("8426")
    files = {f.label: f.files for f in app.step2_fields() if f.kind == "file"}
    assert [Path(p).name for p in files["①領収書・明細書"]] == ["領収書まごころ_202610.pdf"]
    assert [Path(p).name for p in files["介護保険証（介護保険被保険者証）の写し"]] == ["保険証.pdf"]

    app.attach_insurance.set(False)
    assert "介護保険証（介護保険被保険者証）の写し" not in {f.label for f in app.step2_fields()}

    app.save()
    assert load_settings(tmp_path / "settings.json").attachments_dir == str(every)


def test_missing_attachments_are_reported(app, tmp_path):
    app.month2.set("202610")
    app.attach_dir_var.set(str(tmp_path / "none"))
    missing = app.missing_items()
    assert any("①領収書・明細書の添付" in m for m in missing)
    assert any("介護保険証の写しの添付" in m for m in missing)


def test_reissue_reason_asked_from_worker_thread_and_remembered(app, tmp_path, monkeypatch):
    import threading

    import kaigo.gui as gui

    asked = []

    def fake_askstring(title, prompt, initialvalue="", parent=None):
        asked.append((threading.current_thread() is threading.main_thread(), initialvalue))
        return "介護補助金の申請に使用するため"

    monkeypatch.setattr(gui.simpledialog, "askstring", fake_askstring)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("v", app.ask_reissue_reason()))
    t.start()
    for _ in range(100):
        app.root.update()
        if not t.is_alive():
            break
        app.root.after(20)
    t.join(1)
    assert result["v"] == "介護補助金の申請に使用するため"
    assert asked == [(True, "")]  # 画面のスレッドで表示、初回は空欄
    assert load_settings(tmp_path / "settings.json").magokoro_reissue_reason == "介護補助金の申請に使用するため"


def _inside_window(w, root, area=None) -> bool:
    """w が画面（または area の表示範囲）の中に全部見えているか。"""
    root.update()
    box = area or root
    top, bottom = box.winfo_rooty(), box.winfo_rooty() + box.winfo_height()
    return bool(w.winfo_viewable()) and top <= w.winfo_rooty() and w.winfo_rooty() + w.winfo_height() <= bottom


def _check_layout(app):
    root = app.root
    root.update()
    assert root.winfo_height() <= root.winfo_screenheight()
    # 設定タブ: 保存ボタンは常に見える
    app.nb.select(2)
    assert _inside_window(app.save_btn, root)
    # 各タブ: 一番下までスクロールすれば最後の部品が見える
    for i, widget in ((0, app.run1_btn), (1, app.run2_btn)):
        app.nb.select(i)
        sc = app.scrolls[i]
        sc.canvas.yview_moveto(1.0)
        assert _inside_window(widget, root, sc.canvas), f"tab {i}: 最後のボタンに届かない"


def test_layout_buttons_reachable(app):
    _check_layout(app)


def test_layout_reachable_at_150_percent_scaling(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("表示環境がありません")
    root.tk.call("tk", "scaling", float(root.tk.call("tk", "scaling")) * 1.5)
    try:
        a = App(root, settings_file=tmp_path / "s.json")
        _check_layout(a)
    finally:
        root.destroy()
