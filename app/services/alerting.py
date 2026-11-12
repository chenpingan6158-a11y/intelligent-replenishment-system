"""预警扫描服务：低库存 / 断货风险 / 临期 / 滞销。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import NEAR_EXPIRY_RATIO, SLOW_MOVING_DAYS
from ..models import Alert, AlertType, Product, Stock, StockBatch, Store
from . import replenishment, units


def _has_open(db: Session, store_id: int, product_id: int, alert_type: str) -> bool:
    return (
        db.execute(
            select(Alert.id).where(
                Alert.store_id == store_id,
                Alert.product_id == product_id,
                Alert.alert_type == alert_type,
                Alert.status == "OPEN",
            )
        ).first()
        is not None
    )


def _raise_alert(db: Session, store_id: int, product_id: int, alert_type: str, level: str, message: str) -> Alert | None:
    if _has_open(db, store_id, product_id, alert_type):
        return None
    alert = Alert(
        store_id=store_id,
        product_id=product_id,
        alert_type=alert_type,
        level=level,
        message=message,
        status="OPEN",
    )
    db.add(alert)
    return alert


def scan_store(db: Session, store_id: int) -> dict:
    """扫描单个门店，返回各类预警的新增数量。"""
    created = {"LOW_STOCK": 0, "STOCKOUT_RISK": 0, "NEAR_EXPIRY": 0, "SLOW_MOVING": 0}
    products = db.execute(select(Product).where(Product.is_active.is_(True))).scalars().all()

    for product in products:
        stock = db.execute(
            select(Stock).where(Stock.store_id == store_id, Stock.product_id == product.id)
        ).scalar_one_or_none()
        if stock is None:
            continue

        suggestion = replenishment.build_suggestion(db, store_id, product.id)
        if suggestion is None:
            continue

        detail = suggestion["detail"]
        available = suggestion["availableBase"]

        # 1) 低库存：可用库存低于补货点
        if available < detail["rop"]:
            alert = _raise_alert(
                db,
                store_id,
                product.id,
                AlertType.LOW_STOCK,
                "WARN",
                f"{product.name} 可用 {units.humanize(db, product, max(0, available))}，"
                f"低于补货点 {units.humanize(db, product, int(detail['rop']))}",
            )
            if alert:
                created["LOW_STOCK"] += 1

        # 2) 断货风险：预计断货天数 <= 提前期 + 1
        days_left = suggestion["stockoutInDays"]
        if days_left is not None and days_left <= 3:
            alert = _raise_alert(
                db,
                store_id,
                product.id,
                AlertType.STOCKOUT_RISK,
                "CRITICAL" if days_left <= 1 else "WARN",
                f"{product.name} 预计 {days_left} 天内断货",
            )
            if alert:
                created["STOCKOUT_RISK"] += 1

        # 3) 滞销：近 30 天消耗为 0 且仍有库存
        consumed = sum(replenishment.history_for(db, store_id, product.id, days=SLOW_MOVING_DAYS).values())
        if consumed == 0 and stock.qty_base > 0:
            alert = _raise_alert(
                db,
                store_id,
                product.id,
                AlertType.SLOW_MOVING,
                "INFO",
                f"{product.name} 近 {SLOW_MOVING_DAYS} 天无消耗，现存 "
                f"{units.humanize(db, product, stock.qty_base)}",
            )
            if alert:
                created["SLOW_MOVING"] += 1

    # 4) 临期：剩余保质期低于阈值比例
    batches = (
        db.execute(
            select(StockBatch).where(StockBatch.store_id == store_id, StockBatch.qty_base > 0)
        )
        .scalars()
        .all()
    )
    today = date.today()
    for batch in batches:
        product = db.get(Product, batch.product_id)
        if product is None or not product.shelf_life_days:
            continue
        remain = (batch.expiry_date - today).days
        if remain < 0:
            message = f"{product.name} 批次 {batch.batch_no} 已过期 {-remain} 天，数量 {units.humanize(db, product, batch.qty_base)}"
            level = "CRITICAL"
        elif remain <= max(1, int(product.shelf_life_days * NEAR_EXPIRY_RATIO)):
            message = f"{product.name} 批次 {batch.batch_no} 仅剩 {remain} 天到期，数量 {units.humanize(db, product, batch.qty_base)}"
            level = "WARN"
        else:
            continue
        alert = _raise_alert(db, store_id, product.id, AlertType.NEAR_EXPIRY, level, message)
        if alert:
            created["NEAR_EXPIRY"] += 1

    db.flush()
    return created


def scan_all(db: Session) -> dict:
    totals = {"LOW_STOCK": 0, "STOCKOUT_RISK": 0, "NEAR_EXPIRY": 0, "SLOW_MOVING": 0, "stores": 0}
    for store in db.execute(select(Store).where(Store.is_active.is_(True))).scalars().all():
        result = scan_store(db, store.id)
        totals["stores"] += 1
        for key in ("LOW_STOCK", "STOCKOUT_RISK", "NEAR_EXPIRY", "SLOW_MOVING"):
            totals[key] += result[key]
    return totals


def list_alerts(db: Session, store_ids: list[int] | None, status: str = "OPEN", alert_type: str = "") -> list[dict]:
    stmt = select(Alert).order_by(Alert.level.desc(), Alert.created_at.desc())
    if store_ids is not None:
        stmt = stmt.where(Alert.store_id.in_(store_ids or [-1]))
    if status:
        stmt = stmt.where(Alert.status == status)
    if alert_type:
        stmt = stmt.where(Alert.alert_type == alert_type)
    rows = db.execute(stmt.limit(300)).scalars().all()
    result = []
    for row in rows:
        product = db.get(Product, row.product_id)
        store = db.get(Store, row.store_id)
        result.append(
            {
                "id": row.id,
                "storeId": row.store_id,
                "storeName": store.name if store else "",
                "productId": row.product_id,
                "productName": product.name if product else "",
                "type": row.alert_type,
                "level": row.level,
                "message": row.message,
                "status": row.status,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return result


def handle_alert(db: Session, alert: Alert, user_id: int, action: str, note: str = "") -> Alert:
    alert.status = "HANDLED" if action.upper() == "HANDLE" else "IGNORED"
    alert.handled_by = user_id
    alert.handled_at = datetime.now().replace(microsecond=0)
    if note:
        alert.message = f"{alert.message}｜处理备注：{note}"
    db.flush()
    return alert


def summary(db: Session, store_ids: list[int] | None) -> dict:
    stmt = select(Alert).where(Alert.status == "OPEN")
    if store_ids is not None:
        stmt = stmt.where(Alert.store_id.in_(store_ids or [-1]))
    rows = db.execute(stmt).scalars().all()
    by_type: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for row in rows:
        by_type[row.alert_type] = by_type.get(row.alert_type, 0) + 1
        by_level[row.level] = by_level.get(row.level, 0) + 1
    return {"total": len(rows), "byType": by_type, "byLevel": by_level}


def purge_resolved(db: Session, store_id: int, product_id: int, alert_type: str) -> None:
    rows = (
        db.execute(
            select(Alert).where(
                Alert.store_id == store_id,
                Alert.product_id == product_id,
                Alert.alert_type == alert_type,
                Alert.status == "OPEN",
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "HANDLED"


__all__ = ["scan_store", "scan_all", "list_alerts", "handle_alert", "summary", "purge_resolved"]
