"""降價追蹤器的進入點。

    python -m tracker                # 查一次，有降價就寄信
    python -m tracker --dry-run      # 只印出狀態，不寄信、不寫檔
    python -m tracker --force        # 不管有沒有降價都寄一封（測信箱設定用）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .discount import TAIPEI, format_rate
from .notify import MailConfig, MailConfigError, send
from .source import FetchError, Snapshot, fetch
from .state import Store

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = ROOT / "state.json"


def decide(snapshot: Snapshot, previous: dict | None, target_price: float | None) -> str | None:
    """要寄信嗎？要的話回傳信裡的第一行，不用寄回 None。"""
    if previous is None:
        return None  # 第一次執行只記錄基準，不打擾
    before = previous.get("effective")
    if before is None or snapshot.effective >= before:
        return None
    if target_price is not None and snapshot.effective > target_price:
        return None  # 有降但還沒到你設的目標價
    if target_price is not None:
        return f"到你設的目標價了（NT${target_price:,.0f} 以下）。"
    return "你在追的這件降價了。"


def describe(snapshot: Snapshot) -> str:
    lines = [
        f"{snapshot.title}",
        f"  定價 NT${snapshot.list_price:,.0f} / 售價 NT${snapshot.price:,.0f} / "
        f"實付 NT${snapshot.effective:,.0f}（約 {format_rate(snapshot.discount_rate)}）",
    ]
    for p in snapshot.active_promotions:
        mark = "*" if p is snapshot.best_promotion else " "
        lines.append(f"  {mark} {p.describe()}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description="追蹤 91app 商品降價並寄信通知")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--dry-run", action="store_true", help="只查詢並印出，不寄信也不寫狀態")
    parser.add_argument("--force", action="store_true", help="不論有無降價都寄信")
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    store = Store(args.state)
    now = datetime.now(tz=TAIPEI)

    mail: MailConfig | None = None
    failures = 0
    sent = 0

    for watch in config.get("watches", []):
        key = watch.get("id") or watch["url"]
        try:
            snapshot = fetch(watch["url"], now)
        except FetchError as exc:
            print(f"[失敗] {key}: {exc}", file=sys.stderr)
            failures += 1
            continue

        print(describe(snapshot))

        previous = store.get(key)
        reason = decide(snapshot, previous, watch.get("target_price"))
        if args.force and reason is None:
            reason = "測試信：目前狀態如下。"

        if reason and not args.dry_run:
            if mail is None:
                try:
                    mail = MailConfig.from_env()
                except MailConfigError as exc:
                    print(f"[失敗] 無法寄信：{exc}", file=sys.stderr)
                    return 2
            send(mail, snapshot, previous, reason)
            print(f"  -> 已寄出通知給 {', '.join(mail.recipients)}")
            sent += 1
        elif reason:
            print(f"  -> （dry-run，略過寄信）{reason}")

        if not args.dry_run:
            store.put(key, snapshot.to_state())

    if not args.dry_run:
        store.save()

    print(f"\n完成：寄出 {sent} 封，失敗 {failures} 項。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
