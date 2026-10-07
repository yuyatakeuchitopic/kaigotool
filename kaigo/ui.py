"""対象年月・対象業者・領収書内容を確認するダイアログ（tkinter）。"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from .receipts import Receipt, find_receipts
from .vendors import VENDORS

YM_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


def month_choices(today: date, n_past: int = 12) -> list[str]:
    """当月から過去 n_past か月分の YYYYMM（新しい順）。毎回今日の日付から計算する。"""
    y, m = today.year, today.month
    out = []
    for _ in range(n_past + 1):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def parse_date(s: str) -> str | None:
    """「20260902」「2026/9/2」「2026-09-02」→ 20260902。不正なら None。"""
    s = s.strip()
    m = re.fullmatch(r"(\d{4})[/\-.年]?(\d{1,2})[/\-.月]?(\d{1,2})日?", s)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%Y%m%d")
    except ValueError:
        return None


def parse_amount(s: str) -> int | None:
    s = re.sub(r"[,，円¥￥\s]", "", s)
    return int(s) if s.isdigit() else None


def _month_combo(parent, tk, ttk, default: str | None):
    months = month_choices(date.today())
    var = tk.StringVar(value=default or months[0])
    # 一覧にない年月も直接入力できる
    ttk.Combobox(parent, textvariable=var, values=months, width=10).grid(row=0, column=1, sticky="w", pady=4)
    return var


def ask_step1(default_month: str | None, default_vendors: list[str]) -> tuple[str, list[str]] | None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: dict = {}
    root = tk.Tk()
    root.title("介護用品 領収書取得（Step1）")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    ttk.Label(frm, text="対象年月").grid(row=0, column=0, sticky="w")
    month_var = _month_combo(frm, tk, ttk, default_month)

    ttk.Label(frm, text="対象").grid(row=1, column=0, sticky="nw")
    vendor_vars = {}
    for i, (key, v) in enumerate(VENDORS.items()):
        var = tk.BooleanVar(value=key in default_vendors)
        ttk.Checkbutton(frm, text=v.label, variable=var).grid(row=1 + i, column=1, sticky="w")
        vendor_vars[key] = var

    def ok():
        ym = month_var.get().strip()
        if not YM_RE.match(ym):
            messagebox.showwarning("入力エラー", "対象年月は YYYYMM 形式（例: 202610）で入力してください。")
            return
        chosen = [k for k, var in vendor_vars.items() if var.get()]
        if not chosen:
            messagebox.showwarning("未選択", "対象を 1 つ以上選んでください。")
            return
        result["value"] = (ym, chosen)
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=1 + len(VENDORS), column=0, columnspan=2, pady=(12, 0))
    ttk.Button(btns, text="実行", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="キャンセル", command=root.destroy).pack(side="left", padx=4)
    root.mainloop()
    return result.get("value")


def ask_step2(receipt_root: Path, default_month: str | None) -> tuple[str, list[Receipt]] | None:
    """年月を選んで領収書を読み込み、日付・金額を確認（修正）してもらう。"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: dict = {}
    state: dict = {"receipts": [], "rows": []}
    root = tk.Tk()
    root.title("介護補助金 申請（Step2）")
    frm = ttk.Frame(root, padding=16)
    frm.grid(sticky="nsew")

    ttk.Label(frm, text="対象年月").grid(row=0, column=0, sticky="w")
    month_var = _month_combo(frm, tk, ttk, default_month)
    folder_var = tk.StringVar()
    ttk.Label(frm, textvariable=folder_var, foreground="gray").grid(row=1, column=0, columnspan=4, sticky="w")

    table = ttk.Frame(frm)
    table.grid(row=2, column=0, columnspan=4, sticky="w", pady=8)
    total_var = tk.StringVar()
    ttk.Label(frm, textvariable=total_var, font=("", 11, "bold")).grid(row=3, column=0, columnspan=4, sticky="w")

    def update_total(*_):
        amounts = [parse_amount(a.get()) for _, _, a in state["rows"]]
        if state["rows"] and all(a is not None for a in amounts):
            total_var.set(f"ご申請合計金額: {sum(amounts):,} 円")
        else:
            total_var.set("ご申請合計金額: （金額を入力してください）")

    def load(*_):
        ym = month_var.get().strip()
        for w in table.winfo_children():
            w.destroy()
        state["rows"], state["receipts"] = [], []
        if not YM_RE.match(ym):
            folder_var.set("対象年月は YYYYMM 形式（例: 202610）で入力してください")
            update_total()
            return
        folder = receipt_root / ym
        state["receipts"] = find_receipts(folder, ym)
        if not folder.is_dir():
            folder_var.set(f"フォルダがありません: {folder}")
        elif not state["receipts"]:
            folder_var.set(f"命名規則どおりの領収書 PDF がありません: {folder}")
        else:
            folder_var.set(str(folder))
        if state["receipts"]:
            for c, h in enumerate(["", "業者", "ファイル", "領収書日付 (YYYYMMDD)", "金額 (円)", ""]):
                ttk.Label(table, text=h).grid(row=0, column=c, sticky="w", padx=4)
        for i, r in enumerate(state["receipts"], start=1):
            d, a = tk.StringVar(value=r.date or ""), tk.StringVar(value="" if r.amount is None else str(r.amount))
            a.trace_add("write", update_total)
            ttk.Label(table, text="①②③④⑤⑥⑦⑧⑨⑩"[i - 1]).grid(row=i, column=0, padx=4)
            ttk.Label(table, text=VENDORS[r.vendor].label).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Label(table, text=r.path.name).grid(row=i, column=2, sticky="w", padx=4)
            ttk.Entry(table, textvariable=d, width=12).grid(row=i, column=3, padx=4)
            ttk.Entry(table, textvariable=a, width=10).grid(row=i, column=4, padx=4)
            ttk.Label(table, text=r.note, foreground="red").grid(row=i, column=5, sticky="w", padx=4)
            state["rows"].append((r, d, a))
        update_total()

    ttk.Button(frm, text="読み込み", command=load).grid(row=0, column=2, padx=4)
    month_var.trace_add("write", lambda *_: root.after(10, load))

    def ok():
        if not state["rows"]:
            messagebox.showwarning("領収書なし", "領収書が見つかりません。対象年月とフォルダを確認してください。")
            return
        out = []
        for r, d, a in state["rows"]:
            ymd, amount = parse_date(d.get()), parse_amount(a.get())
            if ymd is None or amount is None:
                messagebox.showwarning("入力エラー", f"{r.path.name} の日付（YYYYMMDD）と金額（数字）を入力してください。")
                return
            out.append(replace(r, date=ymd, amount=amount, note=""))
        result["value"] = (month_var.get().strip(), out)
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=4, pady=(12, 0))
    ttk.Button(btns, text="申請画面を開いて入力", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="キャンセル", command=root.destroy).pack(side="left", padx=4)
    load()
    root.mainloop()
    return result.get("value")
