"""抓取 91app / NineYi 商品頁並解析價格與促銷活動。

商品頁是 AngularJS 前端，但價格和活動都由伺服器直接寫進
`window.ServerRenderData["SalePageIndexViewModel"]`，所以不需要跑瀏覽器。
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime

from .discount import Coupon, Promotion, coupon_from_json, effective_price, promotion_from_json

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 30

_VIEW_MODEL_ANCHOR = 'window.ServerRenderData["SalePageIndexViewModel"]'
_APP_DATA = re.compile(r"window\.appData\s*=\s*", re.S)


class FetchError(RuntimeError):
    """抓不到或看不懂商品頁。"""


def _get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
    except urllib.error.URLError as exc:
        raise FetchError(f"連不上 {url}：{exc}") from exc
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8", errors="replace")


def _extract_json_object(html: str, anchor: str | re.Pattern) -> dict:
    """從 anchor 之後的第一個 `{` 開始，括號配對切出完整 JSON。

    不能用非貪婪正則：描述欄位裡本來就有大括號和跳脫引號。
    """
    if isinstance(anchor, re.Pattern):
        m = anchor.search(html)
        if not m:
            raise FetchError("找不到頁面資料區塊")
        cursor = m.end()
    else:
        idx = html.find(anchor)
        if idx == -1:
            raise FetchError("找不到頁面資料區塊")
        cursor = idx + len(anchor)

    start = html.find("{", cursor)
    if start == -1:
        raise FetchError("頁面資料區塊格式不符預期")

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])
    raise FetchError("頁面資料區塊沒有正常結束")


def resolve_url(url: str) -> str:
    """把 bmai.app 短網址換成真正的商品頁網址。

    bmai.app 是 JS 轉址頁，沒有 HTTP 3xx，目標網址藏在 window.appData.targetUrl。
    """
    if "bmai.app" not in url:
        return url
    data = _extract_json_object(_get(url), _APP_DATA)
    target = data.get("targetUrl")
    if not target:
        raise FetchError(f"{url} 解不出目標商品頁")
    return target


@dataclass
class Snapshot:
    """某一次查詢到的商品狀態。"""

    sale_page_id: int
    title: str
    url: str
    list_price: float
    price: float
    effective: float
    best_promotion: Promotion | None
    promotions: list[Promotion] = field(default_factory=list)
    coupons: list[Coupon] = field(default_factory=list)
    status: str = ""
    checked_at: datetime | None = None

    @property
    def discount_rate(self) -> float:
        return self.effective / self.list_price if self.list_price else 1.0

    @property
    def active_promotions(self) -> list[Promotion]:
        if self.checked_at is None:
            return list(self.promotions)
        return [p for p in self.promotions if p.is_active(self.checked_at)]

    @property
    def usable_coupons(self) -> list[Coupon]:
        """單買這一件用得到的券，同名只留一張。

        店家常年掛著生日禮、開卡禮這類會員券，門檻遠高於單件價格，
        全列出來只是雜訊。
        """
        seen: set[str] = set()
        out = []
        for c in self.coupons:
            if c.min_spend and c.min_spend > self.effective:
                continue
            if c.name in seen:
                continue
            seen.add(c.name)
            out.append(c)
        return out

    @property
    def unpriced_promotions(self) -> list[Promotion]:
        """進行中、但算不進實付價的活動（沒寫折數，或要湊滿額滿件）。"""
        return [p for p in self.active_promotions if not p.applies_to_single_item]

    def to_state(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "list_price": self.list_price,
            "price": self.price,
            "effective": self.effective,
            "promotion": self.best_promotion.name if self.best_promotion else None,
            "promotion_ids": sorted(p.id for p in self.active_promotions),
            "coupon_codes": sorted(c.key for c in self.coupons),
            "status": self.status,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


def fetch(url: str, now: datetime) -> Snapshot:
    """抓一次商品頁，回傳當下的價格與折扣狀態。"""
    product_url = resolve_url(url)
    model = _extract_json_object(_get(product_url), _VIEW_MODEL_ANCHOR)

    try:
        list_price = float(model["SuggestPrice"])
        price = float(model["Price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"{product_url} 解不出價格") from exc

    promotions = [promotion_from_json(p) for p in model.get("Promotions") or []]
    effective, best = effective_price(price, promotions, now)

    coupons = []
    for shop in model.get("ECoupons") or []:
        for raw in shop.get("ECouponList") or []:
            coupon = coupon_from_json(raw)
            if coupon.is_active(now):
                coupons.append(coupon)

    return Snapshot(
        sale_page_id=model.get("Id", 0),
        title=model.get("Title") or "(無標題)",
        url=product_url,
        list_price=list_price,
        price=price,
        effective=effective,
        best_promotion=best,
        promotions=promotions,
        coupons=coupons,
        status=model.get("StatusDef") or "",
        checked_at=now,
    )
