"""介護費用申請ツール（Step1 領収書取得 / Step2 申請入力）。

起動:  python app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from kaigo.cli import install_command, missing_dependencies


def main() -> int:
    missing = missing_dependencies()
    if missing:
        msg = f"必要なライブラリが入っていません: {', '.join(missing)}\n\n{install_command()}"
        print(msg)
        try:
            from tkinter import Tk, messagebox

            Tk().withdraw()
            messagebox.showerror("ライブラリ不足", msg)
        except Exception:
            pass
        return 1

    from kaigo.gui import main as gui_main

    # 以前の config.toml があれば、初回起動時の既定値として取り込む
    gui_main(legacy_toml=Path(__file__).with_name("config.toml"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
