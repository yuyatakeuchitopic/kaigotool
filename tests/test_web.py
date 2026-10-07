"""ローカルの模擬サイトでブラウザ操作を確認する（実サイトには接続しない）。"""

import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from kaigo.mail import Mail  # noqa: E402
from kaigo.step1 import SUMMARY_FILE, process, write_summary  # noqa: E402
from kaigo.vendors import VENDORS  # noqa: E402

# 同梱ブラウザのバージョンが合わない環境用（例: PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium）
LAUNCH = {"executable_path": os.environ["PW_CHROMIUM_EXECUTABLE"]} if os.environ.get("PW_CHROMIUM_EXECUTABLE") else {}


def _make_pdf() -> bytes:
    """「発行日」「総合計」を含む PDF を作る（まごころ納品書の代わり）。"""
    with sync_playwright() as p:
        b = p.chromium.launch(**LAUNCH)
        page = b.new_page()
        page.set_content("<p>発行日: 2026-09-01</p><p>総合計 ￥8,426</p>")
        data = page.pdf()
        b.close()
    return data


HOMECARE_HTML = """<html><body><h1>納品書 兼 お買上明細書</h1><table>
<tr><td>商品合計</td><td>10,340円</td><td>940円</td></tr>
<tr><td>合計金額</td><td>9,710円</td><td>883円</td></tr></table>
<p>■ご 注 文 日 ：2026 年09 月02 日</p></body></html>"""

MAGOKORO_FORM = """<html><body><form action="/magokoro/login" method="get">
<label for="o">注文番号</label><input id="o" name="order" type="text">
<label for="t">電話番号</label><input id="t" name="tel" type="text">
<button type="submit">ログイン</button></form></body></html>"""

MAGOKORO_MYPAGE = """<html><body><p>注文番号 {order}</p>
<a href="/magokoro/file?order={order}"><button type="button">領収書・納品書を発行する</button></a></body></html>"""


@pytest.fixture(scope="module")
def site():
    pdf = _make_pdf()
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str, extra=None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/homecare":
                self._send(HOMECARE_HTML.encode(), "text/html; charset=utf-8")
            elif u.path == "/magokoro":
                self._send(MAGOKORO_FORM.encode(), "text/html; charset=utf-8")
            elif u.path == "/magokoro/login":
                seen["order"], seen["tel"] = q.get("order"), q.get("tel")
                self._send(MAGOKORO_MYPAGE.format(order=q.get("order")).encode(), "text/html; charset=utf-8")
            elif u.path == "/magokoro/file":
                self._send(pdf, "application/pdf", {"Content-Disposition": 'attachment; filename="d.pdf"'})
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()


def test_step1_process_with_mock_site(site, tmp_path):
    base, seen = site
    hc, mg = VENDORS["homecare"], VENDORS["magokoro"]
    mails = {
        "homecare": [
            Mail("1", hc.subject, datetime.fromisoformat("2026-09-02T10:00:00+09:00"),
                 [f"■電子領収書URL\n{base}/homecare\n"]),
        ],
        "magokoro": [
            Mail("2", mg.subject, datetime.fromisoformat("2026-09-01T10:00:00+09:00"),
                 [f"[注文番号] P187507264852054846\n▼納品書ダウンロード用URL▼\n{base}/magokoro\n"]),
            Mail("3", mg.subject, datetime.fromisoformat("2026-09-15T10:00:00+09:00"),
                 [f"[注文番号] P200000000000000001\n▼納品書ダウンロード用URL▼\n{base}/magokoro\n"]),
        ],
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(**LAUNCH)
        ctx = browser.new_context(accept_downloads=True)
        results = process(tmp_path, "202609", mails, lambda headless: ctx, magokoro_phone="09000000000")
        browser.close()

    assert [r.status for r in results] == ["ok", "ok", "ok"]
    assert [r.file for r in results] == [
        "領収書ホームケア_202609.pdf", "領収書まごころ_202609_1.pdf", "領収書まごころ_202609_2.pdf",
    ]
    assert (results[0].receipt_date, results[0].amount) == ("20260902", 9710)
    assert (results[1].receipt_date, results[1].amount) == ("20260901", 8426)
    assert seen["order"] == "P200000000000000001" and seen["tel"] == "09000000000"
    for r in results:
        assert (tmp_path / r.file).read_bytes().startswith(b"%PDF")

    summary = json.loads(write_summary(tmp_path, "202609", results).read_text(encoding="utf-8"))
    assert summary["month"] == "202609" and len(summary["receipts"]) == 3
    assert (tmp_path / SUMMARY_FILE).exists()
