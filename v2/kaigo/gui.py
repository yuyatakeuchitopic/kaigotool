"""介護費用申請ツールの画面（tkinter）。Step1 / Step2 をタブで切り替える。"""

from __future__ import annotations

import contextlib
import queue
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter as tk

from . import __version__, attachments
from .form import SLOT_MARKS, Field, Slot, build_fields
from .inputs import YM_RE, month_choices, parse_amount, parse_date
from .receipts import find_receipts
from .settings import APPLICATION_LABELS, Application, Settings, load_settings, save_settings
from .vendors import VENDORS

N_SLOTS = 5
PRESETS = {"": None, **{v.label: v for v in VENDORS.values()}}
MODE_PDF, MODE_MANUAL = "pdf", "manual"


class _QueueWriter:
    """別スレッドの print をログ欄へ送る。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        self.q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


BG = "#f3f5f8"  # 画面の背景
CARD = "#ffffff"  # 枠の中
ACCENT = "#2f6fd6"  # 主ボタン・見出し
TEXT = "#1f2937"
MUTED = "#6b7280"
BORDER = "#d7dce3"
WARN = "#c0392b"
FONT_CANDIDATES = ("Yu Gothic UI", "Meiryo UI", "Meiryo", "Noto Sans CJK JP", "Noto Sans JP", "TkDefaultFont")


def _font(root, size: int, weight: str = "normal") -> tuple:
    from tkinter import font as tkfont

    if not hasattr(_font, "family"):
        families = set(tkfont.families(root))
        _font.family = next((f for f in FONT_CANDIDATES if f in families), "TkDefaultFont")
    return (_font.family, size, weight)


def _apply_style(root) -> None:
    """見た目を揃える（Windows でも同じ表示になるよう、テーマと色・文字を明示する）。"""
    st = ttk.Style(root)
    st.theme_use("clam")
    base = _font(root, 10)
    st.configure(".", font=base, background=BG, foreground=TEXT, bordercolor=BORDER)
    st.configure("Tab.TFrame", background=BG)
    st.configure("TNotebook", background=BG, borderwidth=0)
    st.configure("TNotebook.Tab", padding=(14, 6), font=_font(root, 10, "bold"), background="#e4e8ee")
    st.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)])
    st.configure("Card.TLabelframe", background=CARD, bordercolor=BORDER, relief="solid", borderwidth=1)
    st.configure("Card.TLabelframe.Label", background=CARD, foreground=ACCENT, font=_font(root, 11, "bold"))
    for name in ("Card.TFrame",):
        st.configure(name, background=CARD)
    for name in ("Card.TLabel", "Card.TCheckbutton", "Card.TRadiobutton"):
        st.configure(name, background=CARD, foreground=TEXT)
    st.map("Card.TCheckbutton", background=[("active", CARD)])
    st.map("Card.TRadiobutton", background=[("active", CARD)])
    st.configure("Head.TLabel", background=CARD, foreground=MUTED, font=_font(root, 9, "bold"))
    st.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=_font(root, 9))
    st.configure("Warn.TLabel", background=CARD, foreground=WARN, font=_font(root, 9))
    st.configure("Total.TLabel", background=CARD, foreground=TEXT, font=_font(root, 12, "bold"))
    st.configure("TButton", padding=(12, 5))
    st.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                 font=_font(root, 10, "bold"), padding=(16, 6))
    st.map("Accent.TButton", background=[("disabled", "#a9bfe6"), ("active", "#2559b0")],
           foreground=[("disabled", "#eef2fa")])
    st.configure("TEntry", fieldbackground="white", padding=3)
    st.map("TCombobox", fieldbackground=[("readonly", "white")], background=[("readonly", "#eef1f5")])
    st.configure("TabHint.TLabel", background=BG, foreground=MUTED, font=_font(root, 9))


class ScrollFrame(ttk.Frame):
    """縦スクロールできる領域。中身は .body に置く（表示倍率が大きい PC でも全項目に届くように）。"""

    def __init__(self, parent):
        super().__init__(parent, style="Tab.TFrame")
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Tab.TFrame", padding=12)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        # マウスホイール（ポインタがこの領域にある間だけ）
        self.bind("<Enter>", lambda _e: self._bind_wheel(True))
        self.bind("<Leave>", lambda _e: self._bind_wheel(False))

    def _bind_wheel(self, on: bool) -> None:
        if on:
            self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
            self.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
            self.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))
        else:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.unbind_all(seq)


class App:
    def __init__(self, root: tk.Tk, settings_file: Path | None = None, legacy_toml: Path | None = None):
        self.root = root
        self.settings_file = settings_file
        self.s = load_settings(settings_file, legacy_toml)
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title(f"介護費用申請ツール {__version__}")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._apply_mode()
        root.after(100, self._drain)
        self._fit_window()

    # ------------------------------------------------------------------ 画面構築
    def _build(self) -> None:
        _apply_style(self.root)
        self.root.configure(background=BG)

        header = tk.Frame(self.root, background=ACCENT)
        header.pack(fill="x")
        tk.Label(header, text="介護費用申請ツール", bg=ACCENT, fg="white",
                 font=_font(self.root, 15, "bold")).pack(side="left", padx=(16, 8), pady=10)
        tk.Label(header, text=__version__, bg=ACCENT, fg="#dbe7fb",
                 font=_font(self.root, 9)).pack(side="left", pady=(14, 8))
        self.status_var = tk.StringVar()
        tk.Label(header, textvariable=self.status_var, bg=ACCENT, fg="white",
                 font=_font(self.root, 9)).pack(side="right", padx=16)

        # ログは下端に固定（タブの中身が多くても潰れないよう先に配置）
        logf = ttk.LabelFrame(self.root, text="ログ", padding=6, style="Card.TLabelframe")
        logf.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.log = tk.Text(logf, height=6, state="disabled", wrap="word", relief="flat",
                           background="#fbfbfc", foreground=TEXT, font=_font(self.root, 9),
                           highlightthickness=1, highlightbackground=BORDER)
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(10, 6))
        self.scrolls = [ScrollFrame(self.nb) for _ in range(2)]
        tab3 = ttk.Frame(self.nb, style="Tab.TFrame")  # 設定: スクロール領域 + 常に見える保存ボタン
        footer = ttk.Frame(tab3, style="Tab.TFrame", padding=(12, 6, 12, 8))
        footer.pack(side="bottom", fill="x")
        settings_scroll = ScrollFrame(tab3)
        settings_scroll.pack(fill="both", expand=True)
        self.scrolls.append(settings_scroll)
        self.nb.add(self.scrolls[0], text="  Step1  領収書を取得  ")
        self.nb.add(self.scrolls[1], text="  Step2  申請サイトに入力  ")
        self.nb.add(tab3, text="  設定  ")
        # 設定タブの変数を先に作る（Step1/Step2 から参照するため）
        self._build_settings(settings_scroll.body, footer)
        self._build_step1(self.scrolls[0].body)
        self._build_step2(self.scrolls[1].body)
        self.nb.select(self.scrolls[1])

    def _fit_window(self) -> None:
        """中身に合わせた大きさにする（画面より大きくなる分はタブ内をスクロール）。"""
        self.root.update_idletasks()
        body_h = max(sc.body.winfo_reqheight() for sc in self.scrolls)
        body_w = max(sc.body.winfo_reqwidth() for sc in self.scrolls)
        for sc in self.scrolls:
            sc.canvas.configure(height=body_h, width=body_w)
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(self.root.winfo_reqwidth(), sw - 40)
        h = min(self.root.winfo_reqheight(), sh - 80)  # タスクバー分を空ける
        self.root.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+10")
        self.root.minsize(min(900, w), min(560, h))

    def _card(self, parent, title: str) -> ttk.LabelFrame:
        card = ttk.LabelFrame(parent, text=title, padding=(12, 8), style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, 10))
        return card

    def _hint(self, parent, text: str, **kw) -> ttk.Label:
        return ttk.Label(parent, text=text, style="Hint.TLabel", justify="left", **kw)

    def _month_combo(self, parent) -> tk.StringVar:
        months = month_choices(date.today())
        var = tk.StringVar(value=months[0])
        ttk.Combobox(parent, textvariable=var, values=months, width=10).pack(side="left", padx=6)
        return var

    def _build_settings(self, f: ttk.Frame, footer: ttk.Frame) -> None:
        # 申請者情報（2 列: 左 介護対象者 / 右 振込口座）
        appf = self._card(f, "申請者情報（Step2 で申請サイトに入力）")
        self.app_vars: dict[str, tk.StringVar] = {}
        names = list(APPLICATION_LABELS)
        half = names.index("bank_code")
        for i, name in enumerate(names):
            col, r = (0, i) if i < half else (2, i - half)
            ttk.Label(appf, text=APPLICATION_LABELS[name], style="Card.TLabel").grid(
                row=r, column=col, sticky="w", padx=(24 if col else 0, 6), pady=2)
            var = tk.StringVar(value=getattr(self.s.application, name))
            ttk.Entry(appf, textvariable=var, width=28).grid(row=r, column=col + 1, sticky="w", pady=2)
            self.app_vars[name] = var
        self._hint(appf, "日付は YYYYMMDD。プルダウンの項目（関係・介護度・口座の種類）は申請サイトの表示と同じ文字で入力").grid(
            row=max(half, len(names) - half), column=0, columnspan=4, sticky="w", pady=(6, 0))

        ff = self._card(f, "フォルダ")
        self.root_var = tk.StringVar(value=self.s.receipt_root)
        self.attach_dir_var = tk.StringVar(value=self.s.attachments_dir)
        for r, (label, var) in enumerate([("領収書フォルダ（この下に YYYYMM）", self.root_var),
                                          ("毎回添付するファイル（介護保険証など）", self.attach_dir_var)]):
            ttk.Label(ff, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(ff, textvariable=var).grid(row=r, column=1, sticky="ew", pady=2)
            ttk.Button(ff, text="参照", command=lambda v=var: self._browse_into(v)).grid(row=r, column=2, padx=(6, 0))
        ff.columnconfigure(1, weight=1)

        mf = self._card(f, "メールからの領収書取得（Step1 で使用）")
        self.gmail_addr = tk.StringVar(value=self.s.gmail_address)
        self.gmail_pw = tk.StringVar(value=self.s.gmail_app_password)
        self.magokoro_phone = tk.StringVar(value=self.s.magokoro_phone)
        for r, (label, var, kw) in enumerate([("Gmail アドレス", self.gmail_addr, {"width": 36}),
                                              ("Gmail アプリ パスワード", self.gmail_pw, {"width": 36, "show": "●"}),
                                              ("電話番号（まごころ ログイン用）", self.magokoro_phone, {"width": 20})]):
            ttk.Label(mf, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(mf, textvariable=var, **kw).grid(row=r, column=1, sticky="w", pady=2)

        uf = self._card(f, "申請サイト")
        ttk.Label(uf, text="申込ページ URL", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.url_var = tk.StringVar(value=self.s.apply_url)
        ttk.Entry(uf, textvariable=self.url_var).grid(row=0, column=1, sticky="ew")
        uf.columnconfigure(1, weight=1)

        self.save_btn = ttk.Button(footer, text="設定を保存（次回の既定値にする）", style="Accent.TButton",
                                   command=self.save)
        self.save_btn.pack(side="left")
        ttk.Label(footer, text="保存先はこの PC の中だけ（%LOCALAPPDATA%\\kaigotool）です", style="TabHint.TLabel").pack(
            side="left", padx=10)

    def _build_step1(self, f: ttk.Frame) -> None:
        c1 = self._card(f, "1. 対象を選ぶ")
        row = ttk.Frame(c1, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="対象年月", style="Card.TLabel").pack(side="left")
        self.month1 = self._month_combo(row)
        vrow = ttk.Frame(c1, style="Card.TFrame")
        vrow.pack(fill="x", pady=(6, 0))
        ttk.Label(vrow, text="対象サイト", style="Card.TLabel").pack(side="left")
        self.vendor_vars: dict[str, tk.BooleanVar] = {}
        for key, v in VENDORS.items():
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(vrow, text=v.label, variable=var, style="Card.TCheckbutton").pack(side="left", padx=(12, 0))
            self.vendor_vars[key] = var
        self.overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(c1, text="既存の領収書ファイルがあってもメールから取り直す（まごころは再発行になります）",
                        variable=self.overwrite, style="Card.TCheckbutton").pack(anchor="w", pady=(8, 0))

        c2 = self._card(f, "2. 取得する")
        self.run1_btn = ttk.Button(c2, text="領収書を取得", style="Accent.TButton", command=self.run_step1)
        self.run1_btn.pack(anchor="w")
        self._hint(c2, (
            "・対象年月のフォルダに命名規則どおりの領収書があれば、その業者は取得しません\n"
            "・まごころ: フォルダ内に他の名前の PDF があれば「領収書まごころ_YYYYMM.pdf」にリネームします\n"
            "・まごころが発行済みの場合は再発行になり、再申請理由を聞いてきます。ブラウザの「確認」はご自身で押してください\n"
            "・Gmail と電話番号は「設定」タブで入力します（メールから取得するときだけ使用）"
        )).pack(anchor="w", pady=(8, 0))

    def _build_step2(self, f: ttk.Frame) -> None:
        rf = self._card(f, "1. 領収書と金額")
        mf = ttk.Frame(rf, style="Card.TFrame")
        mf.pack(fill="x")
        ttk.Label(mf, text="入力方法", style="Card.TLabel").pack(side="left")
        self.mode = tk.StringVar(value=self.s.step2_mode if self.s.step2_mode in (MODE_PDF, MODE_MANUAL) else MODE_PDF)
        ttk.Radiobutton(mf, text="PDF から読み取り、合計を自動計算", value=MODE_PDF, variable=self.mode,
                        command=self._apply_mode, style="Card.TRadiobutton").pack(side="left", padx=(12, 0))
        ttk.Radiobutton(mf, text="画面に入力した内容をそのまま使う", value=MODE_MANUAL, variable=self.mode,
                        command=self._apply_mode, style="Card.TRadiobutton").pack(side="left", padx=(12, 0))

        lf = ttk.Frame(rf, style="Card.TFrame")
        lf.pack(fill="x", pady=(8, 6))
        ttk.Label(lf, text="対象年月", style="Card.TLabel").pack(side="left")
        self.month2 = self._month_combo(lf)
        self.load_btn = ttk.Button(lf, text="PDF から読み込み", command=self.load_pdfs)
        self.load_btn.pack(side="left", padx=(0, 6))
        ttk.Button(lf, text="枠をクリア", command=self.clear_slots).pack(side="left")
        self.pdf_status = tk.StringVar()
        ttk.Label(lf, textvariable=self.pdf_status, style="Hint.TLabel", wraplength=480).pack(side="left", padx=10)

        tf = ttk.Frame(rf, style="Card.TFrame")
        tf.pack(fill="x")
        for c, h in enumerate(["", "種類", "メニューNo.", "メニュー名", "発行年月日", "金額(円)", "備考"]):
            ttk.Label(tf, text=h, style="Head.TLabel").grid(row=0, column=c, sticky="w", padx=3, pady=(0, 2))
        self.slots: list[dict[str, tk.StringVar]] = []
        self.amount_entries: list[ttk.Entry] = []
        for i in range(N_SLOTS):
            row = {k: tk.StringVar() for k in ("preset", "no", "name", "date", "amount", "note")}
            ttk.Label(tf, text=SLOT_MARKS[i], style="Card.TLabel").grid(row=i + 1, column=0, padx=3)
            cb = ttk.Combobox(tf, textvariable=row["preset"], values=list(PRESETS), width=24, state="readonly")
            cb.grid(row=i + 1, column=1, padx=3, pady=2)
            cb.bind("<<ComboboxSelected>>", lambda _e, r=row: self._apply_preset(r))
            ttk.Entry(tf, textvariable=row["no"], width=10).grid(row=i + 1, column=2, padx=3)
            ttk.Entry(tf, textvariable=row["name"], width=38).grid(row=i + 1, column=3, padx=3)
            ttk.Entry(tf, textvariable=row["date"], width=10).grid(row=i + 1, column=4, padx=3)
            ae = ttk.Entry(tf, textvariable=row["amount"], width=9, justify="right")
            ae.grid(row=i + 1, column=5, padx=3)
            self.amount_entries.append(ae)
            ttk.Label(tf, textvariable=row["note"], style="Warn.TLabel", wraplength=260).grid(
                row=i + 1, column=6, sticky="w", padx=3)
            row["amount"].trace_add("write", lambda *_: self._update_total())
            self.slots.append(row)
        self._default_slots()

        totf = ttk.Frame(rf, style="Card.TFrame")
        totf.pack(fill="x", pady=(8, 0))
        ttk.Label(totf, text="ご申請合計金額", style="Total.TLabel").pack(side="left")
        self.total_var = tk.StringVar()
        self.total_entry = ttk.Entry(totf, textvariable=self.total_var, width=12, justify="right",
                                     font=_font(self.root, 12, "bold"))
        self.total_entry.pack(side="left", padx=6)
        ttk.Label(totf, text="円", style="Total.TLabel").pack(side="left")
        self.total_hint = tk.StringVar()
        ttk.Label(totf, textvariable=self.total_hint, style="Hint.TLabel").pack(side="left", padx=10)

        af = self._card(f, "2. ファイル添付")
        self.attach_receipts = tk.BooleanVar(value=True)
        self.attach_insurance = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="①領収書・明細書 … 対象年月フォルダの PDF をすべて添付",
                        variable=self.attach_receipts, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(af, text="介護保険証の写し … 「設定」タブの「毎回添付するファイル」フォルダの PDF を添付",
                        variable=self.attach_insurance, style="Card.TCheckbutton").pack(anchor="w", pady=(2, 0))

        sf = self._card(f, "3. 申請サイトに入力（送信はしません）")
        bf = ttk.Frame(sf, style="Card.TFrame")
        bf.pack(anchor="w")
        ttk.Button(bf, text="① 申請用 Edge を開く", command=self.open_edge).pack(side="left")
        self.run2_btn = ttk.Button(bf, text="② 開いている申請画面に入力", style="Accent.TButton",
                                   command=self.run_step2)
        self.run2_btn.pack(side="left", padx=10)
        self._hint(sf, (
            "①で開いた Edge でご自身でログインし、申込プラン（または申込入力）画面を開いてから②を押してください。\n"
            "入力後の確認と「次へ」はご自身で行います。"
        )).pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------------ Step2 の枠
    def _apply_preset(self, row: dict) -> None:
        v = PRESETS.get(row["preset"].get())
        if v is not None:
            row["no"].set(v.menu_no)
            row["name"].set(v.menu_name)

    def _default_slots(self) -> None:
        for row, v in zip(self.slots, VENDORS.values()):
            row["preset"].set(v.label)
            self._apply_preset(row)

    def clear_slots(self) -> None:
        for row in self.slots:
            for var in row.values():
                var.set("")
        self.pdf_status.set("")
        self._update_total()

    def _apply_mode(self) -> None:
        pdf = self.mode.get() == MODE_PDF
        self.load_btn.configure(state="normal" if pdf else "disabled")
        self.total_entry.configure(state="readonly" if pdf else "normal")
        for e in self.amount_entries:
            e.configure(state="normal" if pdf else "disabled")
        self.total_hint.set("金額欄の合計（自動）" if pdf else "手入力してください")
        self._update_total()

    def _update_total(self) -> None:
        if self.mode.get() != MODE_PDF:
            return
        amounts = [parse_amount(r["amount"].get()) for r in self.slots if self._row_used(r)]
        ok = amounts and all(a is not None for a in amounts)
        self.total_var.set(str(sum(amounts)) if ok else "")
        self.total_hint.set("金額欄の合計（自動）" if ok else "金額欄を入力すると自動計算されます")

    def _row_used(self, row: dict) -> bool:
        """PDF モード: 日付・金額・読み込んだファイルのどれかがある行。手入力モード: 日付がある行。"""
        keys = ("date", "amount", "note") if self.mode.get() == MODE_PDF else ("date",)
        return any(row[k].get().strip() for k in keys)

    def load_pdfs(self) -> None:
        ym = self.month2.get().strip()
        if not YM_RE.match(ym):
            messagebox.showwarning("入力エラー", "対象年月は YYYYMM 形式（例: 202610）で入力してください。")
            return
        folder = Path(self.root_var.get().strip()) / ym
        try:
            receipts = find_receipts(folder, ym)
        except Exception as e:  # pdfplumber 未インストール等
            messagebox.showerror("読み込みエラー", str(e))
            return
        if not receipts:
            self.pdf_status.set(f"領収書 PDF が見つかりません: {folder}")
            return
        self.clear_slots()
        for row, r in zip(self.slots, receipts):
            v = VENDORS[r.vendor]
            row["preset"].set(v.label)
            self._apply_preset(row)
            row["date"].set(r.date or "")
            row["amount"].set("" if r.amount is None else str(r.amount))
            row["note"].set(r.path.name + (f"：{r.note}" if r.note else ""))
        msg = f"{folder.name} フォルダから {len(receipts)} 件読み込みました"
        if len(receipts) > N_SLOTS:
            msg += f"（{N_SLOTS} 件を超えた分は入っていません）"
        self.pdf_status.set(msg)
        self._update_total()

    # ------------------------------------------------------------------ 入力値
    def current_settings(self) -> Settings:
        return Settings(
            receipt_root=self.root_var.get().strip(),
            gmail_address=self.gmail_addr.get().strip(),
            gmail_app_password=self.gmail_pw.get().replace(" ", ""),
            magokoro_phone=self.magokoro_phone.get().strip(),
            browser_channel=self.s.browser_channel,
            apply_url=self.url_var.get().strip(),
            attachments_dir=self.attach_dir_var.get().strip(),
            step2_mode=self.mode.get(),
            application=Application(**{k: v.get().strip() for k, v in self.app_vars.items()}),
        )

    def step2_fields(self) -> list[Field]:
        """画面の内容から入力項目を作る。不備があれば ValueError。"""
        s = self.current_settings()
        slots: list[Slot] = []
        amounts: list[int] = []
        for mark, row in zip(SLOT_MARKS, self.slots):
            no, name, raw_date = (row[k].get().strip() for k in ("no", "name", "date"))
            # 種類だけ選んで日付の無い行は使わない
            if not self._row_used(row):
                continue
            ymd = parse_date(raw_date)
            if ymd is None:
                raise ValueError(f"{mark} の発行年月日を YYYYMMDD で入力してください: {raw_date}")
            if self.mode.get() == MODE_PDF:
                amount = parse_amount(row["amount"].get())
                if amount is None:
                    raise ValueError(f"{mark} の金額を数字で入力してください")
                amounts.append(amount)
            slots.append(Slot(no, name, ymd))

        if self.mode.get() == MODE_PDF:
            total = str(sum(amounts)) if amounts else ""
        else:
            raw = self.total_var.get().strip()
            amount = parse_amount(raw) if raw else None
            if raw and amount is None:
                raise ValueError("ご申請合計金額を数字で入力してください")
            total = "" if amount is None else str(amount)
        for key in ("cert_start", "cert_end"):
            raw = getattr(s.application, key)
            if raw and parse_date(raw) is None:
                raise ValueError(f"{APPLICATION_LABELS[key]} を YYYYMMDD で入力してください: {raw}")
        receipt_files, insurance_files, _ = self.attachments()
        return build_fields(s.application, slots, total, receipt_files, insurance_files)

    def receipt_folder(self) -> Path | None:
        ym = self.month2.get().strip()
        return Path(self.root_var.get().strip()) / ym if YM_RE.match(ym) else None

    def attachments(self) -> tuple[list[Path], list[Path], list[str]]:
        """(①領収書・明細書の添付, 介護保険証の写しの添付, 添付しないファイルの理由)。"""
        notes: list[str] = []
        receipt_files: list[Path] = []
        insurance_files: list[Path] = []
        folder = self.receipt_folder()
        if self.attach_receipts.get() and folder is not None:
            receipt_files, n = attachments.pick(attachments.folder_pdfs(folder))
            notes += n
        if self.attach_insurance.get() and self.attach_dir_var.get().strip():
            insurance_files, n = attachments.pick(attachments.folder_pdfs(Path(self.attach_dir_var.get().strip())))
            notes += n
        return receipt_files, insurance_files, notes

    def missing_items(self) -> list[str]:
        out = [APPLICATION_LABELS[k] for k, v in self.app_vars.items() if not v.get().strip()]
        if not any(r["date"].get().strip() for r in self.slots):
            out.append("領収書（発行年月日）")
        if not self.total_var.get().strip():
            out.append("ご申請合計金額")
        receipt_files, insurance_files, _ = self.attachments()
        if self.attach_receipts.get() and not receipt_files:
            out.append(f"①領収書・明細書の添付（{self.receipt_folder()} に PDF がありません）")
        if self.attach_insurance.get() and not insurance_files:
            out.append(f"介護保険証の写しの添付（{self.attach_dir_var.get().strip()} に PDF がありません）")
        return out

    # ------------------------------------------------------------------ 操作
    def save(self) -> None:
        self.s = self.current_settings()
        path = save_settings(self.s, self.settings_file)
        self.status_var.set(f"保存しました（{path}）")

    def _browse(self) -> None:
        self._browse_into(self.root_var)

    def _browse_into(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(initialdir=var.get() or None)
        if d:
            var.set(str(Path(d)))

    def run_step1(self) -> None:
        ym = self.month1.get().strip()
        vendors = [k for k, v in self.vendor_vars.items() if v.get()]
        s = self.current_settings()
        if not YM_RE.match(ym):
            return messagebox.showwarning("入力エラー", "対象年月は YYYYMM 形式（例: 202610）で入力してください。")
        if not vendors:
            return messagebox.showwarning("入力エラー", "対象サイトを 1 つ以上選んでください。")
        overwrite = self.overwrite.get()

        def task():
            from .step1 import run

            return run(s, ym, vendors, overwrite=overwrite, ask_reason=self.ask_reissue_reason)

        def done(_rc):
            # 取得した月を Step2 に引き継ぐ
            self.month2.set(ym)
            if self.mode.get() == MODE_PDF:
                self.load_pdfs()

        self._start("Step1 領収書取得", task, done)

    def run_step2(self) -> None:
        try:
            fields = self.step2_fields()
        except ValueError as e:
            return messagebox.showwarning("入力エラー", str(e))
        missing = self.missing_items()
        if missing and not messagebox.askyesno(
            "未入力の項目", "次の項目が空欄です（サイトには入力されません）。続けますか？\n\n" + "\n".join(missing)
        ):
            return
        url = self.url_var.get().strip()
        for note in self.attachments()[2]:
            self._log(f"※ {note}\n")

        def task():
            from .step2 import fill_open_window

            return fill_open_window(url, fields)

        self._start("Step2 申請入力", task)

    def open_edge(self) -> None:
        from .step2 import launch_edge

        try:
            launch_edge(self.url_var.get().strip())
        except Exception as e:
            return messagebox.showerror("Edge を起動できません", str(e))
        self._log("申請用の Edge を開きました。ログインして申込プランの画面を開き、②を押してください。\n")

    def ask_reissue_reason(self) -> str | None:
        """（処理中のスレッドから呼ぶ）まごころの再申請理由を画面で聞く。前回の理由を初期値にする。"""
        box: dict = {}
        answered = threading.Event()

        def ui():
            try:
                box["v"] = simpledialog.askstring(
                    "まごころサポート 再発行",
                    "この領収書・納品書は発行済みのため、再発行（再申請）になります。\n"
                    "納品書・領収書再申請理由を入力してください（申請サイトに転記します）。",
                    initialvalue=self.s.magokoro_reissue_reason,
                    parent=self.root,
                )
                if box["v"]:
                    self.s.magokoro_reissue_reason = box["v"].strip()
                    save_settings(self.s, self.settings_file)
            finally:
                answered.set()

        self.q.put(ui)  # 画面の操作は画面のスレッドで行う
        answered.wait()
        return box.get("v")

    def _start(self, title: str, task, done=None) -> None:
        if self.busy:
            return
        self.busy = True
        for b in (self.run1_btn, self.run2_btn):
            b.configure(state="disabled")
        self._log(f"\n===== {title} 開始（版 {__version__}） =====\n")
        writer = _QueueWriter(self.q)

        def worker():
            rc = 1
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    rc = task()
            except Exception:
                self.q.put(traceback.format_exc())
            finally:
                self.q.put(lambda: self._finish(title, rc, done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, title: str, rc: int, done) -> None:
        self.busy = False
        for b in (self.run1_btn, self.run2_btn):
            b.configure(state="normal")
        self._log(f"===== {title} 終了 =====\n")
        if done:
            done(rc)

    def _drain(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                item() if callable(item) else self._log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self.busy and not messagebox.askokcancel("終了確認", "処理中です。終了しますか？"):
            return
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    """Windows の表示スケール（125% など）で文字がぼやけないようにする。"""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass  # Windows 以外・古い Windows では何もしない


def main(legacy_toml: Path | None = None) -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root, legacy_toml=legacy_toml)
    root.mainloop()
