"""ベネフィット・ステーション申請フォームへの入力。

入力欄は画面に表示されている項目名（「①メニュー名」など）を手掛かりに、
その後ろにある最初の入力欄を探して入力する。全角/半角・空白の違いは無視する。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import Application

SLOT_MARKS = "①②③④⑤⑥⑦⑧⑨⑩"


@dataclass
class Field:
    kind: str  # text / select / radio / file
    label: str  # 画面上の項目名（の一部）
    value: str  # file の場合は表示用のファイル名一覧
    files: tuple[str, ...] = ()  # file の場合に添付するファイル


@dataclass
class Slot:
    """申請フォームの ①②③… 1 枠分。"""

    menu_no: str
    menu_name: str
    date: str  # 領収書発行年月日 YYYYMMDD


RECEIPT_ATTACH_LABEL = "①領収書・明細書"
INSURANCE_ATTACH_LABEL = "介護保険証（介護保険被保険者証）の写し"


def file_field(label: str, files: list[Path]) -> Field:
    return Field("file", label, "、".join(f.name for f in files), tuple(str(f) for f in files))


def build_fields(
    app: Application,
    slots: list[Slot],
    total: str,
    receipt_files: list[Path] = (),
    insurance_files: list[Path] = (),
) -> list[Field]:
    """入力する項目の一覧。空欄の項目は入力しない（サイト側の値のまま）。"""
    slots = [s for s in slots if s.menu_no or s.menu_name or s.date]
    if len(slots) > len(SLOT_MARKS):
        raise ValueError(f"領収書の枠は {len(SLOT_MARKS)} 件までです")

    fields = [
        Field("radio", "ご利用規約は、ご確認されましたか", "はい"),
        Field("text", "介護対象者氏名", app.care_name),
        Field("text", "ｶｲｺﾞﾀｲｼｮｳｼｬｼﾒｲ", app.care_name_kana),
        Field("select", "会員様との関係", app.relation),
        Field("select", "要支援・要介護度", app.care_level),
        Field("text", "要介護認定の認定年月日（開始）", app.cert_start),
        Field("text", "要介護認定の有効期限（終了）", app.cert_end),
    ]
    # 空いた行は詰めて ①②③… に割り当てる
    for mark, s in zip(SLOT_MARKS, slots):
        fields += [
            Field("text", f"{mark}メニューNo.", s.menu_no),
            Field("text", f"{mark}メニュー名", s.menu_name),
            Field("text", f"{mark}領収書発行年月日", s.date),
        ]
    fields += [
        Field("text", "ご申請合計金額", total),
        Field("text", "金融機関コード", app.bank_code),
        Field("text", "金融機関名", app.bank_name),
        Field("text", "支店コード", app.branch_code),
        Field("text", "支店名", app.branch_name),
        Field("select", "口座の種類", app.account_type),
        Field("text", "口座番号", app.account_number),
        Field("text", "ｺｳｻﾞﾒｲｷﾞﾆﾝ", app.account_holder),
        Field("radio", "不備の場合は、WEB申請はメールで案内", "はい"),
        Field("radio", "申込合計金額・お支払い金額が0円と表示されます", "はい"),
        file_field(RECEIPT_ATTACH_LABEL, list(receipt_files)),
        file_field(INSURANCE_ATTACH_LABEL, list(insurance_files)),
    ]
    return [f for f in fields if f.value.strip()]  # 空欄・添付なしは入力しない


# label の後ろにある入力欄に data-kaigo-target を付ける。見つからなければ理由を返す。
_MARK_JS = r"""
([label, kind, value]) => {
  const norm = s => (s || '').normalize('NFKC').replace(/\s+/g, '');
  const key = norm(label);
  document.querySelectorAll('[data-kaigo-target]').forEach(e => e.removeAttribute('data-kaigo-target'));
  const ownText = el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('');
  const skip = new Set(['SCRIPT', 'STYLE', 'OPTION', 'SELECT', 'TEXTAREA', 'NOSCRIPT']);
  const visible = el => el.getClientRects().length > 0;
  const hits = Array.from(document.body.querySelectorAll('*'))
    .filter(el => !skip.has(el.tagName) && norm(ownText(el)).includes(key));
  // 入力欄の項目名は短い。説明文中の同じ語句より、短い表示中の要素を優先する
  const short = el => norm(ownText(el)).length <= key.length + 8;
  const anchor = kind === 'radio'
    ? (hits.find(visible) || hits[0])
    : (hits.find(el => short(el) && visible(el)) || hits.find(short) || hits.find(visible) || hits[0]);
  if (!anchor) return 'label-not-found';

  const after = el => anchor.contains(el) ||
    (anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  let target = null;
  if (kind === 'radio') {
    const radios = Array.from(document.querySelectorAll('input[type=radio]')).filter(after);
    if (!radios.length) return 'control-not-found';
    const group = radios.filter(r => r.name === radios[0].name);
    const textOf = r => norm((r.labels && r.labels[0] && r.labels[0].innerText) ||
      (r.parentElement && r.parentElement.innerText) ||
      (r.nextSibling && r.nextSibling.textContent) || r.value);
    const v = norm(value);
    target = group.find(r => textOf(r) === v) || group.find(r => textOf(r).startsWith(v));
    if (!target) return 'option-not-found';
  } else if (kind === 'file') {
    // 「ファイルを選択」ボタンの裏にある input[type=file]（非表示でも可）
    target = Array.from(document.querySelectorAll('input[type=file]')).find(after);
    if (!target) {
      const btn = Array.from(document.querySelectorAll('button, a, label, [role=button], input[type=button]'))
        .filter(after).find(b => norm(b.innerText || b.value).includes(norm('ファイルを選択')));
      if (!btn) return 'control-not-found';
      btn.setAttribute('data-kaigo-target', '1');
      return 'chooser';
    }
    target.setAttribute('data-kaigo-multiple', target.multiple ? '1' : '0');
  } else {
    const sel = kind === 'select' ? 'select' :
      'input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([type=submit]):not([type=button]), textarea';
    target = Array.from(document.querySelectorAll(sel)).find(after);
    if (!target) return 'control-not-found';
    if (kind === 'select') {
      const v = norm(value);
      const opts = Array.from(target.options);
      const opt = opts.find(o => norm(o.text) === v) || opts.find(o => norm(o.text).includes(v));
      if (!opt) return 'option-not-found:' + opts.map(o => o.text.trim()).filter(Boolean).join(' / ');
      target.setAttribute('data-kaigo-option', opt.value);
    }
  }
  target.setAttribute('data-kaigo-target', '1');
  return 'ok';
}
"""

_REASONS = {
    "label-not-found": "項目名が画面に見つかりません",
    "control-not-found": "入力欄が見つかりません",
    "option-not-found": "選択肢が見つかりません",
}


def fill_fields(page, fields: list[Field]) -> list[tuple[Field, str]]:
    """フォームに入力する。入力できなかった項目と理由のリストを返す。"""
    failures: list[tuple[Field, str]] = []
    for f in fields:
        try:
            if f.kind == "file":
                err = _upload(page, f)
                if err:
                    failures.append((f, err))
                continue
            status = page.evaluate(_MARK_JS, [f.label, f.kind, f.value])
            if status != "ok":
                failures.append((f, _reason(status)))
                continue
            el = page.locator("[data-kaigo-target]").first
            el.scroll_into_view_if_needed()
            if f.kind == "text":
                el.fill(f.value)
            elif f.kind == "select":
                el.select_option(value=el.get_attribute("data-kaigo-option"))
            else:
                el.check(force=True)
                if not el.is_checked():
                    failures.append((f, "チェックを入れられませんでした"))
        except Exception as e:
            failures.append((f, f"入力エラー: {e}"))
    return failures


def _reason(status: str) -> str:
    head, _, detail = status.partition(":")
    return _REASONS.get(head, head) + (f"（選択肢: {detail}）" if detail else "")


def _upload(page, f: Field) -> str | None:
    """添付ファイルを選択する。1 回で複数選べない欄には 1 ファイルずつ選ぶ。"""
    pending = list(f.files)
    while pending:
        status = page.evaluate(_MARK_JS, [f.label, "file", ""])
        if status not in ("ok", "chooser"):
            return _reason(status)
        el = page.locator("[data-kaigo-target]").first
        multiple = status == "ok" and el.get_attribute("data-kaigo-multiple") == "1"
        batch = pending if multiple else pending[:1]
        if status == "chooser":
            el.scroll_into_view_if_needed()
            with page.expect_file_chooser() as fc:
                el.click()
            fc.value.set_files(batch)
        else:
            el.set_input_files(batch)
        pending = pending[len(batch):]
        _settle(page)
    return None


def _settle(page) -> None:
    """アップロード処理の完了を少し待つ。"""
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
