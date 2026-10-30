"""用 LINE Messaging API 推播降價通知。

只用標準函式庫。需要兩個環境變數：

    LINE_CHANNEL_ACCESS_TOKEN   LINE Developers 後台的 channel access token
    LINE_TO                     收訊息的 LINE user ID（後台 Basic settings 裡的 Your user ID）
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .discount import format_rate
from .source import Snapshot

PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
MULTICAST_ENDPOINT = "https://api.line.me/v2/bot/message/multicast"
TIMEOUT = 30
MAX_TEXT = 4900  # LINE 單則文字訊息上限 5000 字，留一點餘裕


class LineConfigError(RuntimeError):
    """LINE 設定不完整。"""


class LineSendError(RuntimeError):
    """LINE API 回了錯誤。"""


@dataclass
class LineConfig:
    token: str
    recipients: list[str]

    @classmethod
    def from_env(cls, env: dict | None = None) -> "LineConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO") if not env.get(k)]
        if missing:
            raise LineConfigError("缺少環境變數：" + ", ".join(missing))
        return cls(
            token=env["LINE_CHANNEL_ACCESS_TOKEN"],
            recipients=[a.strip() for a in env["LINE_TO"].split(",") if a.strip()],
        )


def compose(snapshot: Snapshot, previous: dict | None, reason: str) -> str:
    """組一則適合在手機上讀的訊息。"""
    lines = [
        reason,
        "",
        snapshot.title,
        f"現在 NT${snapshot.effective:,.0f}"
        f"（定價 NT${snapshot.list_price:,.0f}，約 {format_rate(snapshot.discount_rate)}）",
    ]
    if previous and previous.get("effective") is not None:
        before = previous["effective"]
        lines.append(f"上次 NT${before:,.0f}，省 NT${before - snapshot.effective:,.0f}")
    if snapshot.best_promotion:
        lines.append(f"折扣：{snapshot.best_promotion.describe()}")

    coupons = snapshot.usable_coupons
    if coupons:
        lines += ["", "這個價位用得到的券（要自己領）："] + [f"・{c.describe()}" for c in coupons]

    lines += ["", snapshot.url]
    text = "\n".join(lines)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def send(config: LineConfig, snapshot: Snapshot, previous: dict | None, reason: str) -> None:
    message = {"type": "text", "text": compose(snapshot, previous, reason)}

    # 一個收件人用 push，多個用 multicast——兩者的 to 欄位型別不同。
    if len(config.recipients) == 1:
        endpoint = PUSH_ENDPOINT
        payload = {"to": config.recipients[0], "messages": [message]}
    else:
        endpoint = MULTICAST_ENDPOINT
        payload = {"to": config.recipients, "messages": [message]}

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).close()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LineSendError(f"LINE API 回應 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise LineSendError(f"連不上 LINE API：{exc}") from exc
