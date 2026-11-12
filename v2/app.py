"""介護費用申請ツール v2（Step1 領収書取得 / Step2 申請入力）。

起動:  python app.py        （exe 版は kaigotool.exe）
動作確認: app.py --selftest 結果.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

from kaigo.cli import ROOT, install_command, missing_dependencies


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--selftest":
        from kaigo.selftest import run

        channel = argv[2] if len(argv) >= 3 else "msedge"
        return run(Path(argv[1]), None if channel == "bundled" else channel)

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
    gui_main(legacy_toml=ROOT / "config.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
