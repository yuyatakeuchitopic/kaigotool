"""Step1: メールから領収書を取得する。

使い方:
    python step1.py                       # ダイアログで対象年月（既定は当月）・業者を選択
    python step1.py --month 202609        # 年月指定（業者は両方）
    python step1.py --month 202609 --vendor magokoro
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kaigo.cli import check_dependencies
from kaigo.config import ConfigError, load_config
from kaigo.vendors import VENDORS


def main() -> int:
    ap = argparse.ArgumentParser(description="Gmail から介護用品の領収書を取得します")
    ap.add_argument("--month", help="対象年月 YYYYMM（省略時はダイアログで選択）")
    ap.add_argument("--vendor", nargs="+", choices=list(VENDORS), help="対象業者（省略時は両方）")
    ap.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    ap.add_argument("--overwrite", action="store_true", help="既存の領収書ファイルも取り直す")
    ap.add_argument("--show-browser", action="store_true", help="まごころのダウンロード操作を画面表示する")
    args = ap.parse_args()

    if not check_dependencies():
        return 1
    try:
        cfg = load_config(args.config)
        cfg.require_gmail()
    except ConfigError as e:
        print(e)
        return 1

    month, vendors = args.month, args.vendor or list(VENDORS)
    if month is None:
        from kaigo.ui import ask_step1

        chosen = ask_step1(None, vendors)
        if chosen is None:
            print("キャンセルしました")
            return 1
        month, vendors = chosen

    from kaigo.step1 import run

    return run(cfg, month, vendors, overwrite=args.overwrite, show_browser=args.show_browser)


if __name__ == "__main__":
    sys.exit(main())
