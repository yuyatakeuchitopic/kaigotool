"""Gmail を IMAP（アプリ パスワード）で検索・取得する。

Gmail 独自の IMAP 拡張 X-GM-RAW を使うと、Gmail の検索窓と同じ構文
（subject:"..." after:... before:...）で検索できる。
"""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser


@dataclass
class Mail:
    uid: str
    subject: str
    date: datetime
    # 本文テキストの候補（text/plain、HTML をテキスト化したもの の順）
    bodies: list[str] = field(default_factory=list)


class GmailImap:
    def __init__(self, address: str, app_password: str, host: str = "imap.gmail.com"):
        self.address = address
        self.app_password = app_password
        self.host = host
        self.conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "GmailImap":
        self.conn = imaplib.IMAP4_SSL(self.host)
        self.conn.login(self.address, self.app_password)
        # アーカイブ済みのメールも対象にするため「すべてのメール」を開く
        self.conn.select(self._all_mail_box(), readonly=True)
        return self

    def __exit__(self, *exc) -> None:
        if self.conn is not None:
            try:
                self.conn.logout()
            finally:
                self.conn = None

    def _all_mail_box(self) -> str:
        """\\All 属性のメールボックス名を返す（言語設定で名前が変わるため）。"""
        typ, lines = self.conn.list()
        if typ == "OK":
            for line in lines:
                if line and b"\\All" in line:
                    return line.rsplit(b' "/" ', 1)[1].decode()
        return "INBOX"

    def search(self, gmail_query: str) -> list[str]:
        self.conn.literal = gmail_query.encode("utf-8")
        typ, data = self.conn.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        if typ != "OK":
            raise RuntimeError(f"Gmail 検索に失敗しました: {typ} {data}")
        return data[0].decode().split() if data and data[0] else []

    def fetch(self, uid: str) -> Mail:
        typ, data = self.conn.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            raise RuntimeError(f"メール取得に失敗しました: uid={uid}")
        return parse_message(uid, email.message_from_bytes(data[0][1]))


def parse_message(uid: str, msg: Message) -> Mail:
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    date = parsedate_to_datetime(msg["Date"])
    plain, html = [], []
    for part in msg.walk():
        if part.is_multipart() or part.get_filename():
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        text = _decode_part(part)
        (plain if ctype == "text/plain" else html).append(text)
    bodies = ["\n".join(plain)] if plain else []
    if html:
        bodies.append(html_to_text("\n".join(html)))
    return Mail(uid=uid, subject=subject, date=date, bodies=bodies)


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = (part.get_content_charset() or "utf-8").lower()
    if charset in ("iso-2022-jp", "csiso2022jp"):
        # 丸数字などの機種依存文字を含むことがあるため拡張版で読む
        charset = "iso2022_jp_ext"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


class _HtmlText(HTMLParser):
    """HTML をテキスト化する。<a href> のリンク先 URL はテキストの直後に残す。"""

    BLOCK = {"br", "p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.hrefs: list[str | None] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "a":
            self.hrefs.append(dict(attrs).get("href"))
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.hrefs:
            href = self.hrefs.pop()
            if href and href.startswith("http"):
                self.out.append(f" {href} ")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    return re.sub(r"\n\s*\n+", "\n", "".join(parser.out))
