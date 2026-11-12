"""库存领域服务。

要点：
  * BR-03 出库采用 FEFO（先到期先出），同效期按入库先后；
  * BR-04 一切库存变动必须落 stock_movement，并与 stock 同事务更新；
  * BR-05 库存更新走乐观锁（version），冲突重试，杜绝并发超卖。
"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    Product,
    Stock,
    StockBatch,
    StockMovement,
    StocktakeItem,
    StocktakeOrder,
    Store,
    TransferOrder,
)
from ..models import MovementType as MT
from . import units

MAX_RETRY = 3


def gen_no(prefix: str) -> str:
    return f"{prefix}{date.today():%Y%m%d}{secrets.token_hex(2).upper()}"


# ------------------------------------------------------------------ 库存读写
def get_stock(db: Session, store_id: int, product_id: int, create: bool = False) -> Stock:
    stock = db.execute(
        select(Stock).where(Stock.store_id == store_id, Stock.product_id == product_id)
    ).scalar_one_or_none()
    if stock is None:
        if not create:
            raise HTTPException(status_code=404, detail="库存记录不存在")
        stock = Stock(store_id=store_id, product_id=product_id, qty_base=0, locked_base=0, version=0)
        db.add(stock)
        db.flush()
    return stock


def available_base(db: Session, store_id: int, product_id: int) -> int:
    """可用库存 = 现存 − 锁定；无库存记录视为 0。"""
    stock = db.execute(
        select(Stock).where(Stock.store_id == store_id, Stock.product_id == product_id)
    ).scalar_one_or_none()
    return (stock.qty_base - stock.locked_base) if stock else 0


def _apply_stock_delta(db: Session, store_id: int, product_id: int, delta: int) -> Stock:
    """以乐观锁方式增减库存，失败重试（BR-05）。"""
    for _ in range(MAX_RETRY):
        stock = get_stock(db, store_id, product_id, create=True)
        expected = stock.version
        new_qty = stock.qty_base + delta
        if new_qty < 0:
            raise HTTPException(
                status_code=400,
                detail=f"库存不足：门店 {store_id} 商品 {product_id} 现存 {stock.qty_base}，需扣减 {abs(delta)}",
            )
        result = db.execute(
            Stock.__table__.update()
            .where(Stock.id == stock.id, Stock.version == expected)
            .values(qty_base=new_qty, version=expected + 1)
        )
        if result.rowcount == 1:
            db.expire(stock)
            return stock
        db.expire_all()  # 版本冲突：重新读取后重试
    raise HTTPException(status_code=409, detail="库存并发冲突，请重试")


def record_movement(
    db: Session,
    *,
    store_id: int,
    product_id: int,
    delta_base: int,
    movement_type: str,
    batch_id: int | None = None,
    unit_cost_cents: int = 0,
    ref_type: str = "",
    ref_no: str = "",
    reason_code: str = "",
    operator_id: int | None = None,
    note: str = "",
) -> StockMovement:
    movement = StockMovement(
        store_id=store_id,
        product_id=product_id,
        batch_id=batch_id,
        movement_type=movement_type,
        qty_base=delta_base,
        unit_cost_cents=unit_cost_cents,
        ref_type=ref_type,
        ref_no=ref_no,
        reason_code=reason_code,
        operator_id=operator_id,
        note=note,
    )
    db.add(movement)
    _apply_stock_delta(db, store_id, product_id, delta_base)
    return movement


def consume_batches_fefo(
    db: Session,
    *,
    store_id: int,
    product_id: int,
    qty_base: int,
    movement_type: str,
    ref_type: str = "",
    ref_no: str = "",
    reason_code: str = "",
    operator_id: int | None = None,
    note: str = "",
) -> list[StockMovement]:
    """按 FEFO 从批次中扣减，生成对应流水。"""
    batches = (
        db.execute(
            select(StockBatch)
            .where(
                StockBatch.store_id == store_id,
                StockBatch.product_id == product_id,
                StockBatch.qty_base > 0,
            )
            .order_by(StockBatch.expiry_date.asc(), StockBatch.created_at.asc(), StockBatch.id.asc())
        )
        .scalars()
        .all()
    )
    remaining = qty_base
    movements: list[StockMovement] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.qty_base, remaining)
        batch.qty_base -= take
        remaining -= take
        movements.append(
            record_movement(
                db,
                store_id=store_id,
                product_id=product_id,
                delta_base=-take,
                movement_type=movement_type,
                batch_id=batch.id,
                ref_type=ref_type,
                ref_no=ref_no,
                reason_code=reason_code,
                operator_id=operator_id,
                note=note,
            )
        )
    if remaining > 0:
        # 汇总库存足够但批次不足（历史数据不一致）时，按无批次出库兜底
        movements.append(
            record_movement(
                db,
                store_id=store_id,
                product_id=product_id,
                delta_base=-remaining,
                movement_type=movement_type,
                ref_type=ref_type,
                ref_no=ref_no,
                reason_code=reason_code,
                operator_id=operator_id,
                note=(note + " [批次不足，按汇总库存出库]").strip(),
            )
        )
    return movements


# ------------------------------------------------------------------ 收货入库
def receive(
    db: Session,
    *,
    store_id: int,
    items: list[dict],
    ref_no: str = "",
    batch_no: str = "",
    production_date: date | None = None,
    operator_id: int | None = None,
    note: str = "配送入库",
) -> list[StockMovement]:
    movements: list[StockMovement] = []
    for item in items:
        product = db.get(Product, item["product_id"])
        if product is None:
            raise HTTPException(status_code=404, detail=f"商品 {item['product_id']} 不存在")
        qty_base = units.to_base(db, product, item["qty"], item.get("unit"))
        prod_date = production_date or date.today()
        expiry = prod_date + timedelta(days=product.shelf_life_days or 1)
        batch = StockBatch(
            store_id=store_id,
            product_id=product.id,
            batch_no=batch_no or gen_no("B"),
            production_date=prod_date,
            expiry_date=expiry,
            qty_base=qty_base,
        )
        db.add(batch)
        db.flush()
        movements.append(
            record_movement(
                db,
                store_id=store_id,
                product_id=product.id,
                delta_base=qty_base,
                movement_type=MT.IN,
                batch_id=batch.id,
                unit_cost_cents=product.unit_price_cents,
                ref_type="PURCHASE_ORDER",
                ref_no=ref_no,
                operator_id=operator_id,
                note=note,
            )
        )
    db.flush()
    return movements


# ------------------------------------------------------------------ 领用出库
def outbound(
    db: Session,
    *,
    store_id: int,
    items: list[dict],
    ref_type: str = "OUT",
    operator_id: int | None = None,
    note: str = "",
) -> list[StockMovement]:
    movements: list[StockMovement] = []
    for item in items:
        product = db.get(Product, item["product_id"])
        if product is None:
            raise HTTPException(status_code=404, detail=f"商品 {item['product_id']} 不存在")
        qty_base = units.to_base(db, product, item["qty"], item.get("unit"))
        if available_base(db, store_id, product.id) < qty_base:
            raise HTTPException(status_code=400, detail=f"商品 {product.name} 可用库存不足")
        movements.extend(
            consume_batches_fefo(
                db,
                store_id=store_id,
                product_id=product.id,
                qty_base=qty_base,
                movement_type=MT.OUT,
                ref_type=ref_type,
                ref_no=gen_no("OUT"),
                operator_id=operator_id,
                note=note,
            )
        )
    db.flush()
    return movements


# ------------------------------------------------------------------ 报损
def loss(
    db: Session,
    *,
    store_id: int,
    items: list[dict],
    reason_code: str,
    operator_id: int | None = None,
    note: str = "",
) -> list[StockMovement]:
    valid = {"EXPIRED", "DAMAGED", "PROCESS_LOSS", "OTHER"}
    if reason_code not in valid:
        raise HTTPException(status_code=400, detail=f"报损原因必须是 {valid} 之一")
    movements: list[StockMovement] = []
    ref_no = gen_no("LOSS")
    for item in items:
        product = db.get(Product, item["product_id"])
        if product is None:
            raise HTTPException(status_code=404, detail=f"商品 {item['product_id']} 不存在")
        qty_base = units.to_base(db, product, item["qty"], item.get("unit"))
        movements.extend(
            consume_batches_fefo(
                db,
                store_id=store_id,
                product_id=product.id,
                qty_base=qty_base,
                movement_type=MT.LOSS,
                ref_type="LOSS",
                ref_no=ref_no,
                reason_code=reason_code,
                operator_id=operator_id,
                note=note,
            )
        )
    db.flush()
    return movements


# ------------------------------------------------------------------ 盘点
def create_stocktake(db: Session, store_id: int, operator_id: int) -> StocktakeOrder:
    order = StocktakeOrder(store_id=store_id, created_by=operator_id, status="DRAFT")
    db.add(order)
    db.flush()
    rows = db.execute(select(Stock).where(Stock.store_id == store_id)).scalars().all()
    for row in rows:
        db.add(
            StocktakeItem(
                stocktake_id=order.id,
                product_id=row.product_id,
                book_qty_base=row.qty_base,
                actual_qty_base=row.qty_base,
            )
        )
    db.flush()
    return order


def confirm_stocktake(
    db: Session,
    *,
    stocktake_id: int,
    items: list[dict],
    operator_id: int | None = None,
) -> list[StockMovement]:
    order = db.get(StocktakeOrder, stocktake_id)
    if order is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    if order.status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="盘点单已确认，不可重复调整")
    movements: list[StockMovement] = []
    for item in items:
        product = db.get(Product, item["product_id"])
        if product is None:
            continue
        actual_base = units.to_base(db, product, item["actual_qty"], item.get("unit"))
        record = db.execute(
            select(StocktakeItem).where(
                StocktakeItem.stocktake_id == stocktake_id,
                StocktakeItem.product_id == product.id,
            )
        ).scalar_one_or_none()
        if record is None:
            record = StocktakeItem(
                stocktake_id=stocktake_id,
                product_id=product.id,
                book_qty_base=0,
                actual_qty_base=0,
            )
            db.add(record)
            db.flush()
        record.actual_qty_base = actual_base
        current = get_stock(db, order.store_id, product.id).qty_base
        delta = actual_base - current
        if delta == 0:
            continue
        if delta < 0:
            movements.extend(
                consume_batches_fefo(
                    db,
                    store_id=order.store_id,
                    product_id=product.id,
                    qty_base=-delta,
                    movement_type=MT.ADJUST,
                    ref_type="STOCKTAKE",
                    ref_no=f"ST{stocktake_id}",
                    operator_id=operator_id,
                    note="盘点盘亏",
                )
            )
        else:
            batch = StockBatch(
                store_id=order.store_id,
                product_id=product.id,
                batch_no=gen_no("ADJ"),
                production_date=date.today(),
                expiry_date=date.today() + timedelta(days=product.shelf_life_days or 1),
                qty_base=delta,
            )
            db.add(batch)
            db.flush()
            movements.append(
                record_movement(
                    db,
                    store_id=order.store_id,
                    product_id=product.id,
                    delta_base=delta,
                    movement_type=MT.ADJUST,
                    batch_id=batch.id,
                    ref_type="STOCKTAKE",
                    ref_no=f"ST{stocktake_id}",
                    operator_id=operator_id,
                    note="盘点盘盈",
                )
            )
    order.status = "CONFIRMED"
    order.confirmed_at = None
    db.flush()
    return movements


# ------------------------------------------------------------------ 调拨
def transfer(
    db: Session,
    *,
    from_store_id: int,
    to_store_id: int,
    product_id: int,
    qty: int,
    unit: str | None = None,
    operator_id: int | None = None,
) -> TransferOrder:
    if from_store_id == to_store_id:
        raise HTTPException(status_code=400, detail="调出与调入门店不能相同")
    for sid in (from_store_id, to_store_id):
        if db.get(Store, sid) is None:
            raise HTTPException(status_code=404, detail=f"门店 {sid} 不存在")
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    qty_base = units.to_base(db, product, qty, unit)
    record = TransferOrder(
        transfer_no=gen_no("TR"),
        from_store_id=from_store_id,
        to_store_id=to_store_id,
        product_id=product_id,
        qty_base=qty_base,
        created_by=operator_id,
    )
    db.add(record)
    db.flush()
    consume_batches_fefo(
        db,
        store_id=from_store_id,
        product_id=product_id,
        qty_base=qty_base,
        movement_type=MT.TRANSFER_OUT,
        ref_type="TRANSFER",
        ref_no=record.transfer_no,
        operator_id=operator_id,
        note=f"调出至门店 {to_store_id}",
    )
    batch = StockBatch(
        store_id=to_store_id,
        product_id=product_id,
        batch_no=gen_no("TRB"),
        production_date=date.today(),
        expiry_date=date.today() + timedelta(days=product.shelf_life_days or 1),
        qty_base=qty_base,
    )
    db.add(batch)
    db.flush()
    record_movement(
        db,
        store_id=to_store_id,
        product_id=product_id,
        delta_base=qty_base,
        movement_type=MT.TRANSFER_IN,
        batch_id=batch.id,
        ref_type="TRANSFER",
        ref_no=record.transfer_no,
        operator_id=operator_id,
        note=f"由门店 {from_store_id} 调入",
    )
    db.flush()
    return record


def close_alerts_for(db: Session, store_id: int, product_id: int, alert_type: str) -> None:
    """库存恢复后自动关闭对应预警。"""
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
        row.handled_at = None
