"""补货建议服务：把数据库状态喂给预测引擎，产出可解释的建议清单。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import FORECAST_HISTORY_DAYS
from ..models import (
    ConsumptionDaily,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    ReplenishmentPolicy,
    Stock,
)
from . import forecast, units

OPEN_STATUSES = (OrderStatus.SUBMITTED, OrderStatus.APPROVED, OrderStatus.CONFIRMED, OrderStatus.RECEIVED)


def in_transit_base(db: Session, store_id: int, product_id: int) -> int:
    """已下单未收货的数量（以最小单位计）。"""
    total = 0
    rows = db.execute(
        select(PurchaseOrderItem.order_qty_base, PurchaseOrderItem.received_qty_base)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.order_id)
        .where(
            PurchaseOrder.store_id == store_id,
            PurchaseOrderItem.product_id == product_id,
            PurchaseOrder.status.in_((OrderStatus.SUBMITTED, OrderStatus.APPROVED, OrderStatus.CONFIRMED)),
        )
    ).all()
    for ordered, received in rows:
        total += max(0, (ordered or 0) - (received or 0))
    return total


def history_for(db: Session, store_id: int, product_id: int, days: int = FORECAST_HISTORY_DAYS + 14) -> dict[date, int]:
    start = date.today() - timedelta(days=days)
    rows = db.execute(
        select(ConsumptionDaily.biz_date, ConsumptionDaily.qty_base).where(
            ConsumptionDaily.store_id == store_id,
            ConsumptionDaily.product_id == product_id,
            ConsumptionDaily.biz_date >= start,
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def _default_policy(store_id: int, product_id: int) -> ReplenishmentPolicy:
    """没有显式策略时的兜底规则。"""
    return ReplenishmentPolicy(
        store_id=store_id,
        product_id=product_id,
        lead_time_days=2,
        order_cycle_days=3,
        moq_base=1,
        pack_multiple_base=1,
        max_stock_base=0,
        service_level_z=165,
        is_enabled=True,
    )


def build_suggestion(db: Session, store_id: int, product_id: int) -> dict | None:
    product = db.get(Product, product_id)
    if product is None:
        return None
    policy = db.execute(
        select(ReplenishmentPolicy).where(
            ReplenishmentPolicy.store_id == store_id,
            ReplenishmentPolicy.product_id == product_id,
        )
    ).scalar_one_or_none() or _default_policy(store_id, product_id)

    stock = db.execute(
        select(Stock).where(Stock.store_id == store_id, Stock.product_id == product_id)
    ).scalar_one_or_none()
    on_hand = stock.qty_base if stock else 0
    locked = stock.locked_base if stock else 0

    inp = forecast.SuggestionInput(
        history=history_for(db, store_id, product_id),
        on_hand=on_hand,
        locked=locked,
        in_transit=in_transit_base(db, store_id, product_id),
        lead_time_days=policy.lead_time_days,
        order_cycle_days=policy.order_cycle_days,
        moq_base=policy.moq_base,
        pack_multiple_base=policy.pack_multiple_base,
        max_stock_base=policy.max_stock_base,
        z=(policy.service_level_z or 165) / 100.0,
        today=date.today(),
        history_days=FORECAST_HISTORY_DAYS,
    )
    sug = forecast.compute_suggestion(inp)
    days_left = forecast.stockout_days(inp)

    return {
        "storeId": store_id,
        "productId": product.id,
        "sku": product.sku,
        "productName": product.name,
        "baseUnit": product.base_unit,
        "orderUnit": product.order_unit,
        "basePerOrderUnit": product.base_per_order_unit,
        "suggestQtyBase": sug.suggest_qty_base,
        "suggestQtyOrder": units.to_order_unit(db, product, sug.suggest_qty_base),
        "availableBase": sug.available_base,
        "availableText": units.humanize(db, product, max(0, sug.available_base)),
        "needsReorder": sug.needs_reorder,
        "stockoutInDays": days_left,
        "reason": sug.reason,
        "detail": sug.detail,
        "unitPriceCents": product.unit_price_cents,
        "amountCents": units.to_order_unit(db, product, sug.suggest_qty_base) * product.unit_price_cents,
    }


def suggestions_for_store(db: Session, store_id: int, only_needed: bool = True) -> list[dict]:
    product_ids = [
        row[0]
        for row in db.execute(select(Product.id).where(Product.is_active.is_(True))).all()
    ]
    result = []
    for pid in product_ids:
        item = build_suggestion(db, store_id, pid)
        if item is None:
            continue
        if only_needed and not (item["needsReorder"] and item["suggestQtyBase"] > 0):
            continue
        result.append(item)
    result.sort(key=lambda x: (x["stockoutInDays"] if x["stockoutInDays"] is not None else 99))
    return result


def consumption_series(db: Session, store_id: int, product_id: int, days: int = 30) -> list[dict]:
    start = date.today() - timedelta(days=days - 1)
    rows = dict(
        db.execute(
            select(ConsumptionDaily.biz_date, ConsumptionDaily.qty_base).where(
                ConsumptionDaily.store_id == store_id,
                ConsumptionDaily.product_id == product_id,
                ConsumptionDaily.biz_date >= start,
            )
        ).all()
    )
    series = []
    cursor = start
    while cursor <= date.today():
        series.append({"date": cursor.isoformat(), "qty": rows.get(cursor, 0), "weekday": cursor.weekday()})
        cursor += timedelta(days=1)
    return series


def refresh_consumption_from_sales(db: Session, store_id: int, biz_date: date) -> int:
    """按配方把某日菜品销量折算为原料消耗（幂等：同日重算覆盖）。"""
    from ..models import Recipe, RecipeItem, SalesDaily

    rows = db.execute(
        select(SalesDaily.recipe_id, func.sum(SalesDaily.qty)).where(
            SalesDaily.store_id == store_id, SalesDaily.biz_date == biz_date
        ).group_by(SalesDaily.recipe_id)
    ).all()
    consumed: dict[int, int] = {}
    for recipe_id, qty in rows:
        items = db.execute(select(RecipeItem).where(RecipeItem.recipe_id == recipe_id)).scalars().all()
        for item in items:
            consumed[item.product_id] = consumed.get(item.product_id, 0) + int(qty) * item.qty_base

    existing = {
        row.product_id: row
        for row in db.execute(
            select(ConsumptionDaily).where(
                ConsumptionDaily.store_id == store_id, ConsumptionDaily.biz_date == biz_date
            )
        ).scalars().all()
    }
    for product_id, qty_base in consumed.items():
        row = existing.get(product_id)
        if row:
            row.qty_base = qty_base
        else:
            db.add(ConsumptionDaily(store_id=store_id, biz_date=biz_date, product_id=product_id, qty_base=qty_base))
    for product_id, row in existing.items():
        if product_id not in consumed:
            row.qty_base = 0
    db.flush()
    return len(consumed)


def sales_volume(db: Session, store_id: int, days: int = 30) -> list[dict]:
    """近 N 天营业额与订单量趋势（菜品销量 × 单价）。"""
    from ..models import Recipe, SalesDaily

    start = date.today() - timedelta(days=days - 1)
    rows = db.execute(
        select(SalesDaily.biz_date, func.sum(SalesDaily.qty), func.sum(SalesDaily.qty * Recipe.price_cents))
        .join(Recipe, Recipe.id == SalesDaily.recipe_id)
        .where(SalesDaily.store_id == store_id, SalesDaily.biz_date >= start)
        .group_by(SalesDaily.biz_date)
    ).all()
    data = {r[0]: {"qty": int(r[1] or 0), "revenueCents": int(r[2] or 0)} for r in rows}
    series = []
    cursor = start
    while cursor <= date.today():
        item = data.get(cursor, {"qty": 0, "revenueCents": 0})
        series.append({"date": cursor.isoformat(), **item})
        cursor += timedelta(days=1)
    return series
