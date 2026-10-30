"""用 SMTP 寄降價通知信。"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from .discount import format_rate
from .source import Snapshot


class MailConfigError(RuntimeError):
    """SMTP 設定不完整。"""


@dataclass
class MailConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipients: list[str]
    use_ssl: bool

    @classmethod
    def from_env(cls, env: dict | None = None) -> "MailConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO") if not env.get(k)]
        if missing:
            raise MailConfigError("缺少環境變數：" + ", ".join(missing))
        port = int(env.get("SMTP_PORT", "587"))
        return cls(
            host=env["SMTP_HOST"],
            port=port,
            user=env["SMTP_USER"],
            password=env["SMTP_PASS"],
            sender=env.get("MAIL_FROM") or env["SMTP_USER"],
            recipients=[a.strip() for a in env["MAIL_TO"].split(",") if a.strip()],
            use_ssl=env.get("SMTP_SSL", "").lower() in ("1", "true", "yes") or port == 465,
        )


def _body(snapshot: Snapshot, previous: dict | None, reason: str) -> tuple[str, str]:
    lines = [
        reason,
        "",
        snapshot.title,
        f"現在：NT${snapshot.effective:,.0f}"
        f"（定價 NT${snapshot.list_price:,.0f}，約 {format_rate(snapshot.discount_rate)}）",
    ]
    if previous and previous.get("effective") is not None:
        before = previous["effective"]
        lines.append(f"上次：NT${before:,.0f}（省了 NT${before - snapshot.effective:,.0f}）")
    if snapshot.best_promotion:
        lines.append(f"折扣來源：{snapshot.best_promotion.describe()}")

    others = [p for p in snapshot.active_promotions if p is not snapshot.best_promotion]
    if others:
        lines += ["", "其他進行中的活動："] + [f"・{p.describe()}" for p in others]

    coupons = snapshot.usable_coupons
    if coupons:
        lines += ["", "這個價位用得到的券（要自己去領）："] + [f"・{c.describe()}" for c in coupons]

    lines += ["", snapshot.url]
    text = "\n".join(lines)

    html_lines = "".join(f"<p>{_escape(l)}</p>" if l else "<br>" for l in lines[:-2])
    html = (
        f"<div style='font-family:-apple-system,\"Noto Sans TC\",sans-serif;line-height:1.6'>"
        f"{html_lines}"
        f"<p><a href='{_escape(snapshot.url)}'>前往商品頁</a></p></div>"
    )
    return text, html


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(config: MailConfig, snapshot: Snapshot, previous: dict | None, reason: str) -> None:
    text, html = _body(snapshot, previous, reason)

    msg = EmailMessage()
    msg["Subject"] = f"降價了：{snapshot.title} NT${snapshot.effective:,.0f}"
    msg["From"] = formataddr(("降價追蹤", config.sender))
    msg["To"] = ", ".join(config.recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if config.use_ssl:
        with smtplib.SMTP_SSL(config.host, config.port, context=context, timeout=30) as smtp:
            smtp.login(config.user, config.password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config.host, config.port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(config.user, config.password)
            smtp.send_message(msg)
