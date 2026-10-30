"""用 ntfy.sh 推播降價通知到手機。

這是設定最少的一條路：不用註冊、不用帳號、不用 API key。
手機裝 ntfy App、訂閱一個頻道名稱，就能收到。

    NTFY_TOPIC    頻道名稱（等同密碼，不要公開——放 GitHub Secrets）
    NTFY_SERVER   自架伺服器網址，省略則用 https://ntfy.sh
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .discount import format_rate
from .source import Snapshot

DEFAULT_SERVER = "https://ntfy.sh"
TIMEOUT = 30


class PushConfigError(RuntimeError):
    """ntfy 設定不完整。"""


class PushSendError(RuntimeError):
    """ntfy 回了錯誤。"""


@dataclass
class PushConfig:
    topic: str
    server: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "PushConfig":
        env = os.environ if env is None else env
        topic = env.get("NTFY_TOPIC")
        if not topic:
            raise PushConfigError("缺少環境變數：NTFY_TOPIC")
        return cls(topic=topic, server=(env.get("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/"))


def compose(snapshot: Snapshot, previous: dict | None, reason: str) -> tuple[str, str]:
    """回傳 (標題, 內文)，為手機通知的版面設計。"""
    title = f"降到 NT${snapshot.effective:,.0f}（{format_rate(snapshot.discount_rate)}）"

    lines = [reason, "", snapshot.title]
    if previous and previous.get("effective") is not None:
        before = previous["effective"]
        lines.append(f"上次 NT${before:,.0f}，省 NT${before - snapshot.effective:,.0f}")
    if snapshot.best_promotion:
        lines.append(f"折扣：{snapshot.best_promotion.describe()}")

    coupons = snapshot.usable_coupons
    if coupons:
        lines += ["", "用得到的券（要自己領）："] + [f"・{c.describe()}" for c in coupons]

    return title, "\n".join(lines)


def send(config: PushConfig, snapshot: Snapshot, previous: dict | None, reason: str) -> None:
    title, body = compose(snapshot, previous, reason)
    payload = {
        "topic": config.topic,
        "title": title,
        "message": body,
        "priority": 4,  # 高優先度，手機會跳出來
        "tags": ["moneybag"],
        "click": snapshot.url,  # 點通知直接開商品頁
    }
    req = urllib.request.Request(
        config.server + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).close()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise PushSendError(f"ntfy 回應 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise PushSendError(f"連不上 ntfy：{exc}") from exc
