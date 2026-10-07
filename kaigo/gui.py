"""介護費用申請ツールの画面（tkinter）。Step1 / Step2 をタブで切り替える。"""

from __future__ import annotations

import contextlib
import queue
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

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


class App:
    def __init__(self, root: tk.Tk, settings_file: Path | None = None, legacy_toml: Path | None = None):
        self.root = root
        self.settings_file = settings_file
        self.s = load_settings(settings_file, legacy_toml)
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        root.title("介護費用申請ツール")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._apply_mode()
        root.after(100, self._drain)
        root.minsize(900, 600)

    # ------------------------------------------------------------------ 画面構築
    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="領収書フォルダ").pack(side="left")
        self.root_var = tk.StringVar(value=self.s.receipt_root)
        ttk.Entry(top, textvariable=self.root_var).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(top, text="参照", command=self._browse).pack(side="left")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=12, pady=8)
        tab1, tab2 = ttk.Frame(self.nb, padding=12), ttk.Frame(self.nb, padding=12)
        self.nb.add(tab1, text="  Step1 領収書取得  ")
        self.nb.add(tab2, text="  Step2 申請入力  ")
        self._build_step1(tab1)
        self._build_step2(tab2)
        self.nb.select(tab2)

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 4))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="設定を保存（次回の既定値にする）", command=self.save).pack(side="left")
        self.status_var = tk.StringVar()
        ttk.Label(bottom, textvariable=self.status_var, foreground="gray").pack(side="left", padx=8)

        logf = ttk.LabelFrame(self.root, text="ログ", padding=4)
        logf.pack(fill="both", padx=12, pady=(0, 12))
        self.log = tk.Text(logf, height=9, state="disabled", wrap="word")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _month_combo(self, parent) -> tk.StringVar:
        months = month_choices(date.today())
        var = tk.StringVar(value=months[0])
        ttk.Combobox(parent, textvariable=var, values=months, width=10).pack(side="left", padx=4)
        return var

    def _build_step1(self, f: ttk.Frame) -> None:
        row = ttk.Frame(f)
        row.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(row, text="対象年月").pack(side="left")
        self.month1 = self._month_combo(row)

        ttk.Label(f, text="対象サイト").grid(row=1, column=0, sticky="nw", pady=2)
        self.vendor_vars: dict[str, tk.BooleanVar] = {}
        vf = ttk.Frame(f)
        vf.grid(row=1, column=1, sticky="w")
        for key, v in VENDORS.items():
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(vf, text=v.label, variable=var).pack(anchor="w")
            self.vendor_vars[key] = var

        ttk.Label(f, text="Gmail アドレス").grid(row=2, column=0, sticky="w", pady=2)
        self.gmail_addr = tk.StringVar(value=self.s.gmail_address)
        ttk.Entry(f, textvariable=self.gmail_addr, width=40).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="アプリ パスワード").grid(row=3, column=0, sticky="w", pady=2)
        self.gmail_pw = tk.StringVar(value=self.s.gmail_app_password)
        ttk.Entry(f, textvariable=self.gmail_pw, width=40, show="●").grid(row=3, column=1, sticky="w")

        self.overwrite = tk.BooleanVar(value=False)
        self.show_browser = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="既存の領収書ファイルも取り直す", variable=self.overwrite).grid(
            row=4, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(f, text="まごころの操作をブラウザに表示する（動作確認用）", variable=self.show_browser).grid(
            row=5, column=1, sticky="w")
        self.run1_btn = ttk.Button(f, text="領収書を取得", command=self.run_step1)
        self.run1_btn.grid(row=6, column=1, sticky="w", pady=(12, 0))

    def _build_step2(self, f: ttk.Frame) -> None:
        # 申請者情報（2 列）
        appf = ttk.LabelFrame(f, text="申請者情報", padding=8)
        appf.pack(fill="x")
        self.app_vars: dict[str, tk.StringVar] = {}
        names = list(APPLICATION_LABELS)
        half = names.index("bank_code")  # 左列: 介護対象者 / 右列: 振込口座
        for i, name in enumerate(names):
            col, r = (0, i) if i < half else (2, i - half)
            ttk.Label(appf, text=APPLICATION_LABELS[name]).grid(row=r, column=col, sticky="w", padx=(16 if col else 0, 4))
            var = tk.StringVar(value=getattr(self.s.application, name))
            ttk.Entry(appf, textvariable=var, width=26).grid(row=r, column=col + 1, sticky="w", pady=1)
            self.app_vars[name] = var
        url_row = max(half, len(names) - half)
        ttk.Label(appf, text="申込ページ URL").grid(row=url_row, column=0, sticky="w")
        self.url_var = tk.StringVar(value=self.s.apply_url)
        ttk.Entry(appf, textvariable=self.url_var).grid(row=url_row, column=1, columnspan=3, sticky="ew", pady=1)
        ttk.Label(appf, text="※日付は YYYYMMDD。プルダウン項目は申請サイトの表示と同じ文字で入力",
                  foreground="gray").grid(row=url_row + 1, column=0, columnspan=4, sticky="w")

        # 領収書
        rf = ttk.LabelFrame(f, text="領収書", padding=8)
        rf.pack(fill="x", pady=(8, 0))
        mf = ttk.Frame(rf)
        mf.pack(fill="x")
        ttk.Label(mf, text="入力方法").pack(side="left")
        self.mode = tk.StringVar(value=self.s.step2_mode if self.s.step2_mode in (MODE_PDF, MODE_MANUAL) else MODE_PDF)
        ttk.Radiobutton(mf, text="PDF から読み取り、合計を自動計算", value=MODE_PDF, variable=self.mode,
                        command=self._apply_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mf, text="画面に入力した内容をそのまま使う", value=MODE_MANUAL, variable=self.mode,
                        command=self._apply_mode).pack(side="left")

        lf = ttk.Frame(rf)
        lf.pack(fill="x", pady=4)
        ttk.Label(lf, text="対象年月").pack(side="left")
        self.month2 = self._month_combo(lf)
        self.load_btn = ttk.Button(lf, text="PDF から読み込み", command=self.load_pdfs)
        self.load_btn.pack(side="left", padx=4)
        ttk.Button(lf, text="枠をクリア", command=self.clear_slots).pack(side="left")
        self.pdf_status = tk.StringVar()
        ttk.Label(lf, textvariable=self.pdf_status, foreground="gray", wraplength=520).pack(side="left", padx=8)

        tf = ttk.Frame(rf)
        tf.pack(fill="x")
        for c, h in enumerate(["", "種類", "メニューNo.", "メニュー名", "発行年月日", "金額(円)", "備考"]):
            ttk.Label(tf, text=h).grid(row=0, column=c, sticky="w", padx=2)
        self.slots: list[dict[str, tk.StringVar]] = []
        self.amount_entries: list[ttk.Entry] = []
        for i in range(N_SLOTS):
            row = {k: tk.StringVar() for k in ("preset", "no", "name", "date", "amount", "note")}
            ttk.Label(tf, text=SLOT_MARKS[i]).grid(row=i + 1, column=0, padx=2)
            cb = ttk.Combobox(tf, textvariable=row["preset"], values=list(PRESETS), width=26, state="readonly")
            cb.grid(row=i + 1, column=1, padx=2, pady=1)
            cb.bind("<<ComboboxSelected>>", lambda _e, r=row: self._apply_preset(r))
            ttk.Entry(tf, textvariable=row["no"], width=10).grid(row=i + 1, column=2, padx=2)
            ttk.Entry(tf, textvariable=row["name"], width=40).grid(row=i + 1, column=3, padx=2)
            ttk.Entry(tf, textvariable=row["date"], width=10).grid(row=i + 1, column=4, padx=2)
            ae = ttk.Entry(tf, textvariable=row["amount"], width=9)
            ae.grid(row=i + 1, column=5, padx=2)
            self.amount_entries.append(ae)
            ttk.Label(tf, textvariable=row["note"], foreground="#c0392b", wraplength=300).grid(
                row=i + 1, column=6, sticky="w", padx=2)
            row["amount"].trace_add("write", lambda *_: self._update_total())
            self.slots.append(row)
        self._default_slots()

        totf = ttk.Frame(rf)
        totf.pack(fill="x", pady=(6, 0))
        ttk.Label(totf, text="ご申請合計金額").pack(side="left")
        self.total_var = tk.StringVar()
        self.total_entry = ttk.Entry(totf, textvariable=self.total_var, width=12)
        self.total_entry.pack(side="left", padx=4)
        ttk.Label(totf, text="円").pack(side="left")
        self.total_hint = tk.StringVar()
        ttk.Label(totf, textvariable=self.total_hint, foreground="gray").pack(side="left", padx=8)

        self.run2_btn = ttk.Button(f, text="申請画面を開いて入力（送信はしません）", command=self.run_step2)
        self.run2_btn.pack(anchor="w", pady=(10, 0))

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
            browser_channel=self.s.browser_channel,
            apply_url=self.url_var.get().strip(),
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
        return build_fields(s.application, slots, total)

    def missing_items(self) -> list[str]:
        out = [APPLICATION_LABELS[k] for k, v in self.app_vars.items() if not v.get().strip()]
        if not any(r["date"].get().strip() for r in self.slots):
            out.append("領収書（発行年月日）")
        if not self.total_var.get().strip():
            out.append("ご申請合計金額")
        return out

    # ------------------------------------------------------------------ 操作
    def save(self) -> None:
        self.s = self.current_settings()
        path = save_settings(self.s, self.settings_file)
        self.status_var.set(f"保存しました（{path}）")

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.root_var.get() or None)
        if d:
            self.root_var.set(str(Path(d)))

    def run_step1(self) -> None:
        ym = self.month1.get().strip()
        vendors = [k for k, v in self.vendor_vars.items() if v.get()]
        s = self.current_settings()
        if not YM_RE.match(ym):
            return messagebox.showwarning("入力エラー", "対象年月は YYYYMM 形式（例: 202610）で入力してください。")
        if not vendors:
            return messagebox.showwarning("入力エラー", "対象サイトを 1 つ以上選んでください。")
        if not s.gmail_address or not s.gmail_app_password:
            return messagebox.showwarning("入力エラー", "Gmail アドレスとアプリ パスワードを入力してください。")
        overwrite, show = self.overwrite.get(), self.show_browser.get()

        def task():
            from .step1 import run

            return run(s, ym, vendors, overwrite=overwrite, show_browser=show)

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
        url, channel = self.url_var.get().strip(), self.s.browser_channel

        def task():
            from .step2 import run

            return run(url, fields, channel)

        self._start("Step2 申請入力", task)

    def _start(self, title: str, task, done=None) -> None:
        if self.busy:
            return
        self.busy = True
        for b in (self.run1_btn, self.run2_btn):
            b.configure(state="disabled")
        self._log(f"\n===== {title} 開始 =====\n")
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


def main(legacy_toml: Path | None = None) -> None:
    root = tk.Tk()
    App(root, legacy_toml=legacy_toml)
    root.mainloop()
