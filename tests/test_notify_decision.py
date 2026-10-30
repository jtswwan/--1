import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.__main__ import decide
from tracker.discount import TAIPEI
from tracker.source import Snapshot

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=TAIPEI)


def snap(effective):
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


def test_first_run_is_silent():
    assert decide(snap(1730), None, None) is None


def test_price_drop_notifies():
    assert decide(snap(1533), {"effective": 1730}, None) is not None


def test_same_price_is_silent():
    assert decide(snap(1730), {"effective": 1730}, None) is None


def test_price_rise_is_silent():
    assert decide(snap(2190), {"effective": 1730}, None) is None


def test_drop_above_target_is_silent():
    assert decide(snap(1600), {"effective": 1730}, 1500) is None


def test_drop_to_target_notifies():
    assert decide(snap(1450), {"effective": 1730}, 1500) is not None
