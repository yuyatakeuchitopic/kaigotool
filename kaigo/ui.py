"""対象年月・対象業者を選ぶダイアログ（tkinter）。"""

from __future__ import annotations

from datetime import date

from .vendors import VENDORS


def recent_months(today: date, n: int = 12) -> list[str]:
    """先月から n か月分の YYYYMM（新しい順）。"""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}{m:02d}")
    return out


def ask(default_month: str | None, default_vendors: list[str]) -> tuple[str, list[str]] | None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: dict = {}
    root = tk.Tk()
    root.title("介護用品 領収書取得")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    months = recent_months(date.today())
    if default_month and default_month not in months:
        months.insert(0, default_month)
    ttk.Label(frm, text="対象年月").grid(row=0, column=0, sticky="w")
    month_var = tk.StringVar(value=default_month or months[0])
    ttk.Combobox(frm, textvariable=month_var, values=months, width=10, state="readonly").grid(
        row=0, column=1, sticky="w", pady=4
    )

    ttk.Label(frm, text="対象").grid(row=1, column=0, sticky="nw")
    vendor_vars = {}
    for i, (key, v) in enumerate(VENDORS.items()):
        var = tk.BooleanVar(value=key in default_vendors)
        ttk.Checkbutton(frm, text=v.label, variable=var).grid(row=1 + i, column=1, sticky="w")
        vendor_vars[key] = var

    def ok():
        chosen = [k for k, var in vendor_vars.items() if var.get()]
        if not chosen:
            messagebox.showwarning("未選択", "対象を 1 つ以上選んでください。")
            return
        result["value"] = (month_var.get(), chosen)
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=1 + len(VENDORS), column=0, columnspan=2, pady=(12, 0))
    ttk.Button(btns, text="実行", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="キャンセル", command=root.destroy).pack(side="left", padx=4)
    root.mainloop()
    return result.get("value")
