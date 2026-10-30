"""降價追蹤器的進入點。

    python -m tracker                # 查一次，有降價就寄信
    python -m tracker --dry-run      # 只印出狀態，不寄信、不寫檔
    python -m tracker --force        # 不管有沒有降價都寄一封（測信箱設定用）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import line as line_channel
from . import notify as email_channel
from . import push as push_channel
from .discount import TAIPEI, format_rate
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
    if before is not None and snapshot.effective < before:
        if target_price is not None and snapshot.effective > target_price:
            return None  # 有降但還沒到你設的目標價
        if target_price is not None:
            return f"到你設的目標價了（NT${target_price:,.0f} 以下）。"
        return "你在追的這件降價了。"

    # 價格沒降，但出現了算不出折扣的新活動（例如店家把活動取名「限時優惠」）。
    # 寧可多問一句，也不要整檔活動錯過。
    known = set(previous.get("promotion_ids") or [])
    fresh = [p for p in snapshot.unpriced_promotions if p.id not in known]
    if fresh:
        names = "、".join(p.name for p in fresh)
        return f"出現新活動「{names}」，程式算不出折扣率，可能比現在便宜，麻煩你自己看一下。"

    return None


def describe(snapshot: Snapshot) -> str:
    lines = [
        f"{snapshot.title}",
        f"  定價 NT${snapshot.list_price:,.0f} / 售價 NT${snapshot.price:,.0f} / "
        f"實付 NT${snapshot.effective:,.0f}（約 {format_rate(snapshot.discount_rate)}）",
    ]
    for p in snapshot.active_promotions:
        mark = "*" if p is snapshot.best_promotion else " "
        lines.append(f"  {mark} {p.describe()}")
    for c in snapshot.usable_coupons:
        lines.append(f"  + {c.describe()}")
    return "\n".join(lines)


class _Sender:
    """把兩種通知管道包成同一個介面。"""

    def __init__(self, label: str, config, send_fn):
        self.label = label
        self._config = config
        self._send_fn = send_fn

    def send(self, snapshot: Snapshot, previous: dict | None, reason: str) -> None:
        self._send_fn(self._config, snapshot, previous, reason)


def _auto_channel(env: dict | None = None) -> str:
    """沒指定管道時，照設定好的環境變數決定走哪條。"""
    env = os.environ if env is None else env
    if env.get("NTFY_TOPIC"):
        return "ntfy"
    if env.get("LINE_CHANNEL_ACCESS_TOKEN") and env.get("LINE_TO"):
        return "line"
    if env.get("SMTP_HOST") and env.get("MAIL_TO"):
        return "email"
    return "none"


def _build_sender(channel: str) -> _Sender:
    if channel == "ntfy":
        cfg = push_channel.PushConfig.from_env()
        return _Sender("ntfy 推播", cfg, push_channel.send)
    if channel == "line":
        cfg = line_channel.LineConfig.from_env()
        return _Sender(f"LINE（{len(cfg.recipients)} 位收件人）", cfg, line_channel.send)
    cfg = email_channel.MailConfig.from_env()
    return _Sender(f"email（{', '.join(cfg.recipients)}）", cfg, email_channel.send)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description="追蹤 91app 商品降價並寄信通知")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--dry-run", action="store_true", help="只查詢並印出，不發通知也不寫狀態")
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="照常查詢並發通知，但不寫回 state.json（給沒有寫入權限的排程用）",
    )
    parser.add_argument("--force", action="store_true", help="不論有無降價都寄信")
    parser.add_argument(
        "--notify",
        choices=("auto", "ntfy", "line", "email", "none"),
        default="auto",
        help="走哪條通知管道。auto 看環境變數決定：依序找 NTFY_TOPIC、LINE_*、"
        "SMTP_*，都沒有就不通知（預設 auto）",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="等同 --notify none：照常查詢，但不發通知",
    )
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    store = Store(args.state)
    now = datetime.now(tz=TAIPEI)

    channel = "none" if args.no_email else args.notify
    if channel == "auto":
        channel = _auto_channel()
    sender = None

    failures = 0
    sent = 0
    alerts: list[str] = []

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

        if reason:
            alerts.append(f"NOTIFY: {watch.get('label') or snapshot.title} — {reason} "
                          f"現在 NT${snapshot.effective:,.0f}（{format_rate(snapshot.discount_rate)}）{snapshot.url}")

        if reason and (channel == "none" or args.dry_run):
            print(f"  -> （不發通知：{'dry-run' if args.dry_run else channel}）")
        elif reason:
            if sender is None:
                try:
                    sender = _build_sender(channel)
                except (
                    email_channel.MailConfigError,
                    line_channel.LineConfigError,
                    push_channel.PushConfigError,
                ) as exc:
                    print(f"[失敗] 無法發通知：{exc}", file=sys.stderr)
                    return 2
            try:
                sender.send(snapshot, previous, reason)
            except (line_channel.LineSendError, push_channel.PushSendError) as exc:
                print(f"[失敗] 通知發送失敗：{exc}", file=sys.stderr)
                failures += 1
            else:
                print(f"  -> 已透過 {sender.label} 通知")
                sent += 1

        if not args.dry_run and not args.no_state:
            store.put(key, snapshot.to_state())

    if not args.dry_run and not args.no_state:
        # GitHub 會在 repo 連續 60 天沒有新 commit 時自動停用排程。
        # 每週換一次這個值，確保至少每週有一次 commit 把排程續命。
        store.put("_heartbeat", {"week": now.strftime("%G-W%V")})
        store.save()

    print(f"\n完成：發出 {sent} 則通知，失敗 {failures} 項。")
    for line in alerts:
        print(line)
    if not alerts:
        print("NOTIFY: none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
