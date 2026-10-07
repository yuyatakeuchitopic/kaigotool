"""Step2: ベネフィット・ステーションの介護補助金申請フォームに入力する。

YYYYMM フォルダの領収書 PDF（Step1 で取得 / 手動で保存 どちらでも可）を読み取り、
確認画面で日付・金額をチェックしてから、Edge で申請フォームに入力する。
「次へ」以降（送信）は自動では行わない。

使い方:
    python step2.py                  # ダイアログで対象年月を選択（既定は当月）
    python step2.py --month 202610
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kaigo.cli import check_dependencies
from kaigo.config import ConfigError, load_config


def main() -> int:
    ap = argparse.ArgumentParser(description="介護補助金の申請フォームに入力します")
    ap.add_argument("--month", help="対象年月 YYYYMM（省略時は当月）")
    ap.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    args = ap.parse_args()

    if not check_dependencies():
        return 1
    try:
        cfg = load_config(args.config)
        cfg.require_application()
    except ConfigError as e:
        print(e)
        return 1

    from kaigo.ui import ask_step2

    chosen = ask_step2(cfg.receipt_root, args.month)
    if chosen is None:
        print("キャンセルしました")
        return 1
    _, receipts = chosen

    from kaigo.step2 import run

    return run(cfg, receipts)


if __name__ == "__main__":
    sys.exit(main())
