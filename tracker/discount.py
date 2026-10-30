"""把 91app 的促銷活動名稱解析成實際折扣率。

91app 的 API 不會給折扣後的數字，折扣資訊只寫在活動名稱裡
（例如「【春夏單品】單件79折」），所以只能從中文字面解析。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

_ZHE = re.compile(r"(\d+(?:\.\d+)?)\s*折")
# 需要湊件數才成立的活動：滿2件、第二件、買一送一⋯⋯
_QTY_HINT = re.compile(r"第\s*[2-9二三四五六七八九]\s*件|滿\s*[2-9]\d*\s*件|買\s*\d+\s*送\s*\d+|[兩两三四五]件")
_SINGLE_HINT = re.compile(r"單件|單品單件|不限件數")
# 需要湊金額才成立的活動
_AMOUNT_HINT = re.compile(r"滿額|滿\s*\$?\d+|現折|折抵")


def parse_rate(text: str) -> float | None:
    """從文字中抓出折扣率，抓不到回 None。

    「79折」-> 0.79、「7折」-> 0.7、「8.5折」-> 0.85、「10折」-> 原價不算折扣。
    """
    m = _ZHE.search(text)
    if not m:
        return None
    raw = float(m.group(1))
    if raw <= 0:
        return None
    if raw == 10:
        return None  # 10 折就是原價
    rate = raw / 10 if raw < 10 else raw / 100
    return rate if 0 < rate < 1 else None


def format_rate(rate: float) -> str:
    """照台灣的寫法：0.79 -> 「79折」、0.7 -> 「7折」、0.85 -> 「85折」。"""
    hundredths = round(rate * 100, 1)
    if hundredths % 10 == 0:
        return f"{hundredths / 10:g}折"
    return f"{hundredths:g}折"


@dataclass(frozen=True)
class Promotion:
    """一檔促銷活動。"""

    id: int
    name: str
    engine: str
    start: datetime
    end: datetime
    rate: float | None
    needs_qty: bool
    needs_amount: bool

    @property
    def applies_to_single_item(self) -> bool:
        """單買這一件就能吃到這個折扣嗎？"""
        return self.rate is not None and not self.needs_qty and not self.needs_amount

    def is_active(self, now: datetime) -> bool:
        return self.start <= now <= self.end

    def describe(self) -> str:
        if self.rate is not None and self.applies_to_single_item:
            suffix = f"（{format_rate(self.rate)}）"
        elif self.needs_amount:
            suffix = "（需湊滿額）"
        elif self.needs_qty:
            suffix = "（需湊件數）"
        else:
            suffix = ""
        return f"{self.name}{suffix}，至 {self.end:%Y-%m-%d}"


def _parse_dt(raw: str) -> datetime:
    """91app 吐的是台北時間的 naive 字串。"""
    return datetime.fromisoformat(raw).replace(tzinfo=TAIPEI)


def promotion_from_json(raw: dict) -> Promotion:
    name = raw.get("Name") or ""
    return Promotion(
        id=raw.get("PromotionId", 0),
        name=name,
        engine=raw.get("PromotionEngineType") or "",
        start=_parse_dt(raw["StartDateTime"]),
        end=_parse_dt(raw["EndDateTime"]),
        rate=parse_rate(name),
        needs_qty=bool(_QTY_HINT.search(name)) and not _SINGLE_HINT.search(name),
        needs_amount=bool(_AMOUNT_HINT.search(name)),
    )


def effective_price(price: float, promotions: list[Promotion], now: datetime) -> tuple[float, Promotion | None]:
    """買一件實際要付多少，以及是哪檔活動給的折扣。

    只採用單件就適用的折扣；滿額、滿件的活動不列入計算，因為算不準。
    """
    candidates = [p for p in promotions if p.is_active(now) and p.applies_to_single_item]
    if not candidates:
        return price, None
    best = min(candidates, key=lambda p: p.rate)
    # 用四捨五入（而非 Python 的銀行家捨入），跟店家結帳一致
    return math.floor(price * best.rate + 0.5), best
