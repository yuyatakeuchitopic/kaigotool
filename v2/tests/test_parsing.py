from datetime import datetime
from email.message import EmailMessage

from kaigo.extract import magokoro_order_number, url_after
from kaigo.mail import Mail, parse_message
from kaigo.receipts import parse_homecare, parse_magokoro
from kaigo.step1 import JST, file_names, gmail_query, month_range, select_mails
from kaigo.vendors import VENDORS

# まごころ PDF を pdfplumber で抽出した実テキストの一部（「⽇」「⾏」は康熙部首の文字）
MAGOKORO_PDF_TEXT = """領領 収収 書書 領収書番号: t7031669
注⽂番号: P187507264852054846
発⾏⽇: 2026-09-01
¥ 8,426-
合計（税込） ￥8,426
送料（税込） ￥0
0 0 総合計 ￥8,426
"""

# ホームケア電子領収書ページの本文テキスト（表はタブ区切り）
HOMECARE_PAGE_TEXT = """納品書 兼 お買上明細書
商品合計\t10,340円\t940円
送料\t715円\t65円\t10%
ベネフィット・ステーション会員割引\t1,345円
合計金額\t9,710円\t883円
10%対象 値引き後\t9,710円\t883円
■ご 注 文 日 ：2026 年09 月02 日
■ご注文番号 ：008517
"""


def test_parse_magokoro():
    info = parse_magokoro(MAGOKORO_PDF_TEXT)
    assert (info.date, info.amount) == ("20260901", 8426)


def test_parse_homecare_uses_total_row_subtotal_column():
    info = parse_homecare(HOMECARE_PAGE_TEXT)
    assert (info.date, info.amount) == ("20260902", 9710)


def test_magokoro_order_number_and_url():
    body = (
        "ご注文ありがとうございました。\n[注文番号]\nP187507264852054846\n"
        "▼納品書ダウンロード用URL▼\nhttps://example.com/receipt?x=1\n"
    )
    assert magokoro_order_number([body]) == "P187507264852054846"
    assert url_after([body], "納品書ダウンロード用URL") == "https://example.com/receipt?x=1"


def test_homecare_url_from_html_mail():
    msg = EmailMessage()
    msg["Subject"] = VENDORS["homecare"].subject
    msg["Date"] = "Wed, 02 Sep 2026 10:00:00 +0900"
    msg.set_content("HTML メールです")
    msg.add_alternative(
        '<p>■電子領収書ＵＲＬ<br><a href="https://shop.example.jp/r/abc">こちら</a></p>'
        '<p>■その他 <a href="https://shop.example.jp/other">x</a></p>',
        subtype="html",
    )
    mail = parse_message("1", msg)
    assert mail.subject == VENDORS["homecare"].subject
    assert url_after(mail.bodies, "電子領収書URL") == "https://shop.example.jp/r/abc"


def test_month_range_and_query():
    start, end = month_range("202612")
    assert start == datetime(2026, 12, 1, tzinfo=JST)
    assert end == datetime(2027, 1, 1, tzinfo=JST)
    q = gmail_query(VENDORS["magokoro"], "202609")
    assert q.startswith('subject:"まごころサポート for ベネフィット・ステーション" after:')


def test_select_mails_filters_subject_and_month_and_sorts():
    v = VENDORS["magokoro"]

    def mail(uid, subject, iso):
        return Mail(uid=uid, subject=subject, date=datetime.fromisoformat(iso))

    mails = [
        mail("1", v.subject, "2026-09-20T10:00:00+09:00"),
        mail("2", "【まごころサポート for ベネフィット・ステーション】発送のお知らせ", "2026-09-03T10:00:00+09:00"),
        mail("3", v.subject, "2026-09-03T10:00:00+09:00"),
        mail("4", v.subject, "2026-08-31T23:30:00+09:00"),  # 前月（日本時間）
        mail("5", v.subject, "2026-08-31T16:00:00+00:00"),  # = 9/1 01:00 JST
    ]
    assert [m.uid for m in select_mails(v, "202609", mails)] == ["5", "3", "1"]


def test_file_names():
    v = VENDORS["homecare"]
    assert file_names(v, "202609", 1) == ["領収書ホームケア_202609.pdf"]
    assert file_names(v, "202609", 2) == ["領収書ホームケア_202609_1.pdf", "領収書ホームケア_202609_2.pdf"]
