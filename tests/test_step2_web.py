"""模擬の申込ページで Step2 の画面操作を確認する（実サイトには接続しない）。"""

import os
import socket
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from kaigo.form import Slot, build_fields  # noqa: E402
from kaigo.settings import Application  # noqa: E402
from kaigo.step2 import fill_open_window, fill_page, launch_edge  # noqa: E402

LAUNCH = {"executable_path": os.environ["PW_CHROMIUM_EXECUTABLE"]} if os.environ.get("PW_CHROMIUM_EXECUTABLE") else {}

PLAN = """<html><body><h1>介護補助金サービス</h1><div style="height:1500px"></div>
<button onclick="setTimeout(()=>location.href='/form', 300)">申し込む</button></body></html>"""


def _text(label, name, required=True):
    badge = '<span class="req">必須</span>' if required else ""
    return f'<div class="row"><div class="lbl">{label} {badge}</div><input type="text" name="{name}"></div>'


def _radio(question, name):
    return (f'<div class="q"><p>{question}</p>'
            f'<label><input type="radio" name="{name}" value="1">はい</label>'
            f'<label><input type="radio" name="{name}" value="0">いいえ</label></div>')


def _select(label, name, options):
    opts = "".join(f"<option value='v{i}'>{o}</option>" for i, o in enumerate(["選択してください", *options]))
    return f'<div class="row"><div class="lbl">{label}</div><select name="{name}">{opts}</select></div>'


FORM = "".join([
    "<html><body><h2>店舗・施設からの質問事項</h2>",
    "<p>ご申請合計金額は領収書の合計を入力してください。</p>",  # 説明文（入力欄ではない）
    _radio("◆ご利用規約は、ご確認されましたか。", "terms"),
    _text("介護対象者　氏名", "name"),
    _text("ｶｲｺﾞﾀｲｼｮｳｼｬ　ｼﾒｲ", "kana"),
    _select("会員様との関係", "rel", ["配偶者", "父母", "（義）祖父母"]),
    _select("要支援・要介護 度", "level", ["要支援1", "要介護4", "要介護5"]),
    _text("要介護認定の認定年月日（開始）", "start"),
    _text("要介護認定の有効期限（終了）", "end"),
    *[_text(f"{m}メニューNo.", f"no{i}", False) + _text(f"{m}メニュー名", f"menu{i}", i == 1)
      + _text(f"{m}領収書発行年月日", f"date{i}", i == 1) for i, m in enumerate("①②③", 1)],
    '<div class="row"><div class="lbl">ご申請合計金額</div>計￥<input type="text" name="total"></div>',
    _text("金融機関コード", "bcode"), _text("金融機関名", "bname"),
    _text("支店コード", "brcode"), _text("支店名", "brname"),
    _select("口座の種類", "atype", ["普通", "当座"]),
    _text("口座番号", "anum"), _text("ｺｳｻﾞﾒｲｷﾞﾆﾝ", "aholder"),
    _radio("不備の場合は、WEB申請はメールで案内・郵送申請は電話で案内いたします。", "defect"),
    _radio("ご入力の最終画面にて、申込合計金額・お支払い金額が0円と表示されますがご申請金額・補助金額とは関係の無い表記となります。", "zero"),
    "<button>次へ</button></body></html>",
])


@pytest.fixture(scope="module")
def site():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = {"/plan": PLAN, "/form": FORM}.get(self.path)
            if body is None:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


APP = Application(
    care_name="介護　花子", care_name_kana="ｶｲｺﾞ　ﾊﾅｺ", relation="（義）祖父母", care_level="要介護5",
    cert_start="20250129", cert_end="20280131", bank_code="0009", bank_name="ﾃｽﾄｷﾞﾝｺｳ",
    branch_code="111", branch_name="ﾃｽﾄｼﾃﾝ", account_type="普通", account_number="1234567",
    account_holder="ﾃｽﾄﾀﾛｳ",
)
SLOTS = [
    Slot("10640022", "フランスベッド ホームケア全科オンライン", "20261002"),
    Slot("10640395", "介護用品の通信販売 まごころサポート(「リフレ」紙おむつ)など", "20261001"),
]


VALUES_JS = """() => Object.fromEntries(Array.from(document.querySelectorAll('input,select'))
    .filter(e => e.type !== 'radio' || e.checked)
    .map(e => [e.name, e.tagName === 'SELECT' ? e.options[e.selectedIndex].text : e.value]))"""


def _fill(site, fields, start="/plan"):
    with sync_playwright() as p:
        browser = p.chromium.launch(**LAUNCH)
        page = browser.new_page()
        page.goto(f"{site}{start}")
        failures = fill_page(page, fields)
        values = page.evaluate(VALUES_JS)
        browser.close()
    return failures, values


def test_open_and_fill(site):
    failures, values = _fill(site, build_fields(APP, SLOTS, "18136"))
    assert failures == []
    assert values == {
        "terms": "1", "name": "介護　花子", "kana": "ｶｲｺﾞ　ﾊﾅｺ", "rel": "（義）祖父母", "level": "要介護5",
        "start": "20250129", "end": "20280131",
        "no1": "10640022", "menu1": "フランスベッド ホームケア全科オンライン", "date1": "20261002",
        "no2": "10640395", "menu2": "介護用品の通信販売 まごころサポート(「リフレ」紙おむつ)など", "date2": "20261001",
        "no3": "", "menu3": "", "date3": "",
        "total": "18136", "bcode": "0009", "bname": "ﾃｽﾄｷﾞﾝｺｳ", "brcode": "111", "brname": "ﾃｽﾄｼﾃﾝ",
        "atype": "普通", "anum": "1234567", "aholder": "ﾃｽﾄﾀﾛｳ", "defect": "1", "zero": "1",
    }


def test_blank_values_are_not_entered_and_bad_option_reported(site):
    app = Application(care_name="介護　花子", relation="存在しない続柄")
    failures, values = _fill(site, build_fields(app, SLOTS[1:], ""))
    assert [(f.label, r.split("（")[0]) for f, r in failures] == [("会員様との関係", "選択肢が見つかりません")]
    assert values["name"] == "介護　花子" and values["kana"] == "" and values["total"] == ""
    assert values["menu1"].startswith("介護用品の通信販売") and values["date1"] == "20261001"


def test_form_page_already_open_is_filled_directly(site):
    failures, values = _fill(site, build_fields(APP, SLOTS, "18136"), start="/form")
    assert failures == [] and values["total"] == "18136"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(not LAUNCH, reason="PW_CHROMIUM_EXECUTABLE（CDP 接続テスト用のブラウザ）未指定")
def test_attach_to_already_open_browser(site, tmp_path, monkeypatch):
    """「申請用 Edge を開く」で開いたブラウザ（ツールが操作していない普通の起動）に後から接続して入力する。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    port = _free_port()
    launch_edge(f"{site}/plan", port=port, exe=LAUNCH["executable_path"], extra_args=["--headless=new", "--no-sandbox"])
    try:
        for _ in range(50):  # 起動待ち
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        time.sleep(1)
        assert fill_open_window(f"{site}/plan", build_fields(APP, SLOTS, "18136"), port=port) == 0

        # 接続を切ってもブラウザとページは残り、入力値が入っている
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            page = [pg for c in browser.contexts for pg in c.pages if "/form" in pg.url][0]
            values = page.evaluate(VALUES_JS)
            automated = page.evaluate("() => navigator.webdriver")
            browser.close()
        assert values["total"] == "18136" and values["date2"] == "20261001" and values["zero"] == "1"
        assert automated is False  # 普通に起動したブラウザなので「自動操作中」と判定される目印が無い
    finally:
        os.system(f"pkill -f 'remote-debugging-port={port}' > /dev/null 2>&1")


def test_attach_reports_when_no_browser(capsys):
    assert fill_open_window("https://example.com/", [], port=_free_port()) == 1
    assert "申請用の Edge に接続できません" in capsys.readouterr().out
