"""智能补货接口。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..database import get_db
from ..deps import allowed_store_ids, ensure_store_access, get_current_user, user_store_id
from ..models import Product, ReplenishmentPolicy, User
from ..services import forecast, replenishment
from ..services import units

router = APIRouter(prefix="/api/replenishment", tags=["智能补货"])


@router.get("/suggestions", summary="门店补货建议清单")
def suggestions(
    store_id: int | None = None,
    only_needed: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = store_id or user_store_id(user)
    ensure_store_access(db, user, sid)
    return ok(replenishment.suggestions_for_store(db, sid, only_needed=only_needed))


@router.get("/{store_id}/{product_id}", summary="单品建议明细（可解释性）")
def detail(
    store_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_store_access(db, user, store_id)
    item = replenishment.build_suggestion(db, store_id, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    product = db.get(Product, product_id)
    assert product is not None
    policy = db.query(ReplenishmentPolicy).filter_by(store_id=store_id, product_id=product_id).one_or_none()
    item["policy"] = (
        {
            "leadTimeDays": policy.lead_time_days,
            "orderCycleDays": policy.order_cycle_days,
            "moqBase": policy.moq_base,
            "packMultipleBase": policy.pack_multiple_base,
            "maxStockBase": policy.max_stock_base,
            "serviceLevelZ": policy.service_level_z,
        }
        if policy
        else None
    )
    return ok(item)


@router.get("/series", summary="消耗曲线（含星期分布）")
def series(
    product_id: int,
    store_id: int | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = store_id or user_store_id(user)
    ensure_store_access(db, user, sid)
    data = replenishment.consumption_series(db, sid, product_id, days)
    return ok(
        {
            "series": data,
            "avg": round(sum(d["qty"] for d in data) / max(1, len(data)), 1),
            "max": max((d["qty"] for d in data), default=0),
        }
    )


@router.post("/backtest", summary="滚动回测：对比建议补货与真实消耗")
def backtest(
    product_id: int,
    store_id: int | None = None,
    days: int = 60,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = store_id or user_store_id(user)
    ensure_store_access(db, user, sid)
    policy_row = db.query(ReplenishmentPolicy).filter_by(store_id=sid, product_id=product_id).one_or_none()
    policy = {
        "lead_time_days": policy_row.lead_time_days if policy_row else 2,
        "order_cycle_days": policy_row.order_cycle_days if policy_row else 3,
        "moq_base": policy_row.moq_base if policy_row else 1,
        "pack_multiple_base": policy_row.pack_multiple_base if policy_row else 1,
        "max_stock_base": policy_row.max_stock_base if policy_row else 0,
        "history_days": 28,
    }
    history = replenishment.history_for(db, sid, product_id, days=days + 40)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    result = forecast.backtest(history, policy=policy, start=start, end=end, initial_stock=policy["moq_base"] * 2)
    product = db.get(Product, product_id)
    result["policy"] = policy
    result["productName"] = product.name if product else ""
    result["stockoutRateText"] = f"{result['shortageRate'] * 100:.1f}%"
    result["avgStockText"] = units.humanize(db, product, int(result["avgStock"])) if product else ""
    return ok(result)


@router.get("/history", summary="补货建议历史快照（用于回溯）")
def history_snapshot(
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = store_id or user_store_id(user)
    ensure_store_access(db, user, sid)
    items = replenishment.suggestions_for_store(db, sid, only_needed=True)
    groups: dict[str, int] = {}
    for item in items:
        days_left = item["stockoutInDays"]
        key = "3天内断货" if days_left is not None and days_left <= 3 else "需补货"
        groups[key] = groups.get(key, 0) + 1
    return ok({"total": len(items), "groups": groups, "generatedAt": date.today().isoformat()})
