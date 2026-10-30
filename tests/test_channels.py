import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.__main__ import _auto_channel
from tracker.discount import TAIPEI
from tracker.push import PushConfig, PushConfigError, compose
from tracker.source import Snapshot

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=TAIPEI)


def _snap(effective=1533):
    return Snapshot(
        sale_page_id=1,
        title="裙子",
        url="https://example.test/1",
        list_price=2190,
        price=2190,
        effective=effective,
        best_promotion=None,
        promotions=[],
        checked_at=NOW,
    )


def test_auto_prefers_ntfy():
    env = {"NTFY_TOPIC": "abc", "SMTP_HOST": "x", "MAIL_TO": "y"}
    assert _auto_channel(env) == "ntfy"


def test_auto_falls_back_to_line_then_email():
    assert _auto_channel({"LINE_CHANNEL_ACCESS_TOKEN": "t", "LINE_TO": "u"}) == "line"
    assert _auto_channel({"SMTP_HOST": "x", "MAIL_TO": "y"}) == "email"


def test_auto_returns_none_when_nothing_configured():
    assert _auto_channel({}) == "none"


def test_push_config_requires_topic():
    try:
        PushConfig.from_env({})
    except PushConfigError:
        pass
    else:
        raise AssertionError("少了 NTFY_TOPIC 應該要報錯")


def test_push_config_defaults_to_ntfy_sh():
    assert PushConfig.from_env({"NTFY_TOPIC": "t"}).server == "https://ntfy.sh"


def test_push_config_strips_trailing_slash():
    cfg = PushConfig.from_env({"NTFY_TOPIC": "t", "NTFY_SERVER": "https://my.ntfy/"})
    assert cfg.server == "https://my.ntfy"


def test_compose_puts_price_in_title():
    title, body = compose(_snap(), {"effective": 1730}, "降價了")
    assert "1,533" in title
    assert "省 NT$197" in body
