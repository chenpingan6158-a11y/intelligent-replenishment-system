"""经营指标服务：缺货率、周转天数、损耗率、订货达成率。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ConsumptionDaily,
    MovementType,
    OrderStatus,
    Product,
    PurchaseOrder,
    Stock,
    StockMovement,
)
from . import replenishment


def _scope_filter(stmt, column, store_ids: list[int] | None):
    if store_ids is not None:
        return stmt.where(column.in_(store_ids or [-1]))
    return stmt


def stockout_rate(db: Session, store_ids: list[int] | None) -> dict:
    """缺货率 = 可用库存 <= 0 的 SKU 数 / 有库存记录的 SKU 数（按门店-商品统计）。"""
    stmt = select(Stock.qty_base, Stock.locked_base)
    stmt = _scope_filter(stmt, Stock.store_id, store_ids)
    rows = db.execute(stmt).all()
    total = len(rows)
    zero = sum(1 for qty, locked in rows if (qty - locked) <= 0)
    return {"total": total, "zero": zero, "rate": round(zero / total, 4) if total else 0.0}


def turnover_days(db: Session, store_ids: list[int] | None, days: int = 30) -> dict:
    """周转天数 = 当前库存 / 近 30 天日均消耗。"""
    start = date.today() - timedelta(days=days)
    stock_stmt = select(func.sum(Stock.qty_base))
    stock_stmt = _scope_filter(stock_stmt, Stock.store_id, store_ids)
    total_stock = db.execute(stock_stmt).scalar() or 0

    cons_stmt = select(func.sum(ConsumptionDaily.qty_base)).where(ConsumptionDaily.biz_date >= start)
    cons_stmt = _scope_filter(cons_stmt, ConsumptionDaily.store_id, store_ids)
    total_consumed = db.execute(cons_stmt).scalar() or 0

    daily_avg = total_consumed / days if days else 0
    days_of_supply = round(total_stock / daily_avg, 1) if daily_avg > 0 else None
    return {"stockBase": int(total_stock), "consumedBase": int(total_consumed), "dailyAvg": round(daily_avg, 1), "turnoverDays": days_of_supply}


def loss_rate(db: Session, store_ids: list[int] | None, days: int = 30) -> dict:
    """损耗率 = 报损金额 / (报损金额 + 出库金额)。"""
    start = date.today() - timedelta(days=days)
    loss_stmt = (
        select(func.sum(func.abs(StockMovement.qty_base) * StockMovement.unit_cost_cents))
        .where(StockMovement.movement_type == MovementType.LOSS, StockMovement.created_at >= start)
    )
    loss_stmt = _scope_filter(loss_stmt, StockMovement.store_id, store_ids)
    loss_amount = int(db.execute(loss_stmt).scalar() or 0)

    out_stmt = (
        select(func.sum(func.abs(StockMovement.qty_base) * StockMovement.unit_cost_cents))
        .where(StockMovement.movement_type.in_((MovementType.OUT, MovementType.LOSS)), StockMovement.created_at >= start)
    )
    out_stmt = _scope_filter(out_stmt, StockMovement.store_id, store_ids)
    out_amount = int(db.execute(out_stmt).scalar() or 0)

    return {
        "lossCents": loss_amount,
        "outCents": out_amount,
        "rate": round(loss_amount / out_amount, 4) if out_amount else 0.0,
    }


def order_fulfillment(db: Session, store_ids: list[int] | None, days: int = 30) -> dict:
    """订货达成率 = 已收货订单数 / 已提交订单数。"""
    start = date.today() - timedelta(days=days)
    base = select(func.count(PurchaseOrder.id)).where(PurchaseOrder.created_at >= start)
    base = _scope_filter(base, PurchaseOrder.store_id, store_ids)
    total = db.execute(base).scalar() or 0

    recv = select(func.count(PurchaseOrder.id)).where(
        PurchaseOrder.created_at >= start,
        PurchaseOrder.status.in_((OrderStatus.RECEIVED, OrderStatus.CLOSED)),
    )
    recv = _scope_filter(recv, PurchaseOrder.store_id, store_ids)
    received = db.execute(recv).scalar() or 0

    return {"total": int(total), "received": int(received), "rate": round(received / total, 4) if total else 0.0}


def top_moving(db: Session, store_ids: list[int] | None, days: int = 30, limit: int = 8) -> list[dict]:
    start = date.today() - timedelta(days=days)
    stmt = (
        select(ConsumptionDaily.product_id, func.sum(ConsumptionDaily.qty_base).label("total"))
        .where(ConsumptionDaily.biz_date >= start)
        .group_by(ConsumptionDaily.product_id)
        .order_by(func.sum(ConsumptionDaily.qty_base).desc())
        .limit(limit)
    )
    stmt = _scope_filter(stmt, ConsumptionDaily.store_id, store_ids)
    result = []
    for product_id, total in db.execute(stmt).all():
        product = db.get(Product, product_id)
        if product:
            result.append({"productId": product_id, "productName": product.name, "totalBase": int(total or 0)})
    return result


def consumption_trend(db: Session, store_ids: list[int] | None, days: int = 14) -> list[dict]:
    start = date.today() - timedelta(days=days - 1)
    stmt = (
        select(ConsumptionDaily.biz_date, func.sum(ConsumptionDaily.qty_base))
        .where(ConsumptionDaily.biz_date >= start)
        .group_by(ConsumptionDaily.biz_date)
        .order_by(ConsumptionDaily.biz_date)
    )
    stmt = _scope_filter(stmt, ConsumptionDaily.store_id, store_ids)
    data = {row[0]: int(row[1] or 0) for row in db.execute(stmt).all()}
    series = []
    cursor = start
    while cursor <= date.today():
        series.append({"date": cursor.isoformat(), "qty": data.get(cursor, 0)})
        cursor += timedelta(days=1)
    return series


def overview(db: Session, store_ids: list[int] | None, store_id: int | None = None) -> dict:
    scope = [store_id] if store_id else store_ids
    return {
        "stockout": stockout_rate(db, scope),
        "turnover": turnover_days(db, scope),
        "loss": loss_rate(db, scope),
        "fulfillment": order_fulfillment(db, scope),
        "topMoving": top_moving(db, scope),
        "consumptionTrend": consumption_trend(db, scope),
        "salesTrend": replenishment.sales_volume(db, store_id or (scope[0] if scope else 0), days=14),
    }
