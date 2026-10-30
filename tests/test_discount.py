import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.discount import TAIPEI, effective_price, parse_rate, promotion_from_json


def test_parse_rate_two_digits():
    assert parse_rate("【春夏單品】單件79折") == 0.79


def test_parse_rate_single_digit():
    assert parse_rate("全館7折") == 0.7


def test_parse_rate_decimal():
    assert parse_rate("8.5折起") == 0.85


def test_parse_rate_ten_is_not_a_discount():
    assert parse_rate("10折") is None


def test_parse_rate_without_discount_text():
    assert parse_rate("【官網限定】雙11預購會，滿額現折再送券") is None
    assert parse_rate("加購限定優惠款") is None


def _promo(name, engine="DiscountReachPieceWithRate", start="2026-10-16T00:00:00", end="2026-10-31T23:59:59.997"):
    return promotion_from_json(
        {"PromotionId": 1, "Name": name, "PromotionEngineType": engine, "StartDateTime": start, "EndDateTime": end}
    )


def test_single_item_promotion_applies():
    assert _promo("【春夏單品】單件79折").applies_to_single_item


def test_amount_threshold_promotion_does_not_apply_to_one_item():
    p = _promo("【官網限定】雙11預購會，滿額現折再送券", engine="DiscountReachPriceWithAmount")
    assert not p.applies_to_single_item


def test_quantity_promotion_does_not_apply_to_one_item():
    assert not _promo("第二件5折").applies_to_single_item
    assert not _promo("滿2件8折").applies_to_single_item


def test_effective_price_uses_best_single_item_rate():
    now = datetime(2026, 10, 30, 9, 0, tzinfo=TAIPEI)
    promos = [_promo("單件79折"), _promo("單件75折"), _promo("第二件5折")]
    price, best = effective_price(2190, promos, now)
    assert price == 1643  # 2190 * 0.75
    assert best.name == "單件75折"


def test_expired_promotion_is_ignored():
    now = datetime(2026, 11, 5, 9, 0, tzinfo=TAIPEI)
    price, best = effective_price(2190, [_promo("單件79折")], now)
    assert price == 2190
    assert best is None


def test_no_promotions_means_full_price():
    now = datetime(2026, 10, 30, 9, 0, tzinfo=TAIPEI)
    assert effective_price(2190, [], now) == (2190, None)


def test_format_rate_matches_taiwanese_convention():
    from tracker.discount import format_rate

    assert format_rate(0.79) == "79折"
    assert format_rate(0.7) == "7折"
    assert format_rate(0.85) == "85折"
    assert format_rate(1.0) == "10折"
