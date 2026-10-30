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


def _promo(pid, name, engine="DiscountReachPriceWithAmount"):
    from tracker.discount import promotion_from_json

    return promotion_from_json(
        {
            "PromotionId": pid,
            "Name": name,
            "PromotionEngineType": engine,
            "StartDateTime": "2026-10-16T00:00:00",
            "EndDateTime": "2026-11-30T23:59:59.997",
        }
    )


def test_new_unpriceable_promotion_notifies():
    """店家把活動取名成沒有折數的「限時優惠」時，寧可多問一句也不要錯過。"""
    s = snap(1730)
    s.promotions = [_promo(999, "限時優惠")]
    reason = decide(s, {"effective": 1730, "promotion_ids": []}, None)
    assert reason is not None
    assert "限時優惠" in reason


def test_already_seen_promotion_does_not_notify_again():
    s = snap(1730)
    s.promotions = [_promo(999, "限時優惠")]
    assert decide(s, {"effective": 1730, "promotion_ids": [999]}, None) is None


def test_new_promotion_with_parseable_rate_is_not_double_reported():
    """能算出折扣的活動由降價邏輯處理，不走「算不出折扣」這條。"""
    s = snap(1730)
    s.promotions = [_promo(999, "單件79折", engine="DiscountReachPieceWithRate")]
    assert decide(s, {"effective": 1730, "promotion_ids": []}, None) is None
