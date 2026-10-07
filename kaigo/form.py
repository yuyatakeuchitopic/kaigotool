"""ベネフィット・ステーション申請フォームへの入力。

入力欄は画面に表示されている項目名（「①メニュー名」など）を手掛かりに、
その後ろにある最初の入力欄を探して入力する。全角/半角・空白の違いは無視する。
"""

from __future__ import annotations

from dataclasses import dataclass

from .settings import Application

SLOT_MARKS = "①②③④⑤⑥⑦⑧⑨⑩"


@dataclass
class Field:
    kind: str  # text / select / radio
    label: str  # 画面上の項目名（の一部）
    value: str


@dataclass
class Slot:
    """申請フォームの ①②③… 1 枠分。"""

    menu_no: str
    menu_name: str
    date: str  # 領収書発行年月日 YYYYMMDD


def build_fields(app: Application, slots: list[Slot], total: str) -> list[Field]:
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
    ]
    return [f for f in fields if f.value.strip()]


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
            status = page.evaluate(_MARK_JS, [f.label, f.kind, f.value])
            if status != "ok":
                head, _, detail = status.partition(":")
                failures.append((f, _REASONS.get(head, head) + (f"（選択肢: {detail}）" if detail else "")))
                continue
            el = page.locator("[data-kaigo-target]").first
            el.scroll_into_view_if_needed()
            if f.kind == "text":
                el.fill(f.value)
            elif f.kind == "select":
                el.select_option(value=el.get_attribute("data-kaigo-option"))
            else:
                el.check(force=True)
        except Exception as e:
            failures.append((f, f"入力エラー: {e}"))
    return failures
