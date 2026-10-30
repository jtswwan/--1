import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.discount import TAIPEI, coupon_from_json
from tracker.source import Snapshot

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=TAIPEI)


def _coupon(code, name, min_spend, amount=200.0):
    return coupon_from_json(
        {
            "Code": code,
            "Name": name,
            "DiscountPrice": amount,
            "DiscountPercent": 0,
            "ECouponUsingMinPrice": min_spend,
            "StartDateTime": "2026-10-01T00:00:00",
            "EndDateTime": "2026-12-31T23:59:59.997",
        }
    )


def _snap(effective, coupons):
    return Snapshot(
        sale_page_id=1,
        title="裙子",
        url="https://example.test/1",
        list_price=2190,
        price=2190,
        effective=effective,
        best_promotion=None,
        promotions=[],
        coupons=coupons,
        checked_at=NOW,
    )


def test_coupon_above_threshold_is_hidden():
    """滿 3000 的生日禮券，買一件 1730 的裙子用不到。"""
    s = _snap(1730, [_coupon("A", "【生日禮】好友卡$500券", 3000)])
    assert s.usable_coupons == []


def test_coupon_within_threshold_is_shown():
    s = _snap(1730, [_coupon("A", "【LINE好友】$200券", 1000)])
    assert len(s.usable_coupons) == 1


def test_coupon_without_threshold_is_shown():
    s = _snap(1730, [_coupon("A", "【客服禮券】", 0)])
    assert len(s.usable_coupons) == 1


def test_duplicate_coupon_names_collapse():
    """同一檔活動常發好幾張代碼不同、名稱相同的券。"""
    s = _snap(
        1730,
        [_coupon("A", "滿額再送200券x1", 1000), _coupon("B", "滿額再送200券x1", 1000)],
    )
    assert len(s.usable_coupons) == 1


def test_describe_mentions_amount_and_threshold():
    text = _coupon("A", "【LINE好友】$200券", 1000).describe()
    assert "NT$200" in text and "NT$1,000" in text
