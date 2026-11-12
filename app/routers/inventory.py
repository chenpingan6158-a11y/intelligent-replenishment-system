"""库存接口：查询、入库、出库、报损、盘点、调拨。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..database import get_db
from ..deps import allowed_store_ids, ensure_store_access, get_current_user, require_roles, user_store_id
from ..models import (
    Category,
    Product,
    Role,
    Stock,
    StockBatch,
    StockMovement,
    StocktakeOrder,
    Store,
    User,
)
from ..schemas import LossIn, OutboundIn, ReceiveIn, StocktakeIn, TransferIn
from ..services import inventory as inv
from ..services import units

router = APIRouter(prefix="/api/inventory", tags=["库存"])


def _resolve_store(db: Session, user: User, store_id: int | None) -> int:
    sid = store_id or user_store_id(user)
    ensure_store_access(db, user, sid)
    return sid


@router.get("/stock", summary="门店库存列表")
def list_stock(
    store_id: int | None = None,
    keyword: str = "",
    only_low: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = _resolve_store(db, user, store_id)
    stmt = select(Stock, Product).join(Product, Product.id == Stock.product_id).where(Stock.store_id == sid)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((Product.name.like(like)) | (Product.sku.like(like)))
    rows = db.execute(stmt.order_by(Product.id)).all()
    result = []
    for stock, product in rows:
        category = db.get(Category, product.category_id)
        available = stock.qty_base - stock.locked_base
        result.append(
            {
                "productId": product.id,
                "sku": product.sku,
                "productName": product.name,
                "categoryName": category.name if category else "",
                "baseUnit": product.base_unit,
                "orderUnit": product.order_unit,
                "qtyBase": stock.qty_base,
                "availableBase": available,
                "qtyText": units.humanize(db, product, stock.qty_base),
                "availableText": units.humanize(db, product, max(0, available)),
                "storageType": product.storage_type,
                "valueCents": int(stock.qty_base / max(1, product.base_per_order_unit) * product.unit_price_cents),
                "updatedAt": stock.updated_at.isoformat() if stock.updated_at else None,
            }
        )
    if only_low:
        result = [r for r in result if r["availableBase"] <= 0]
    return ok(result)


@router.get("/batches", summary="批次库存（FEFO 顺序）")
def list_batches(
    store_id: int | None = None,
    product_id: int | None = None,
    only_expiring: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = _resolve_store(db, user, store_id)
    stmt = select(StockBatch).where(StockBatch.store_id == sid, StockBatch.qty_base > 0)
    if product_id:
        stmt = stmt.where(StockBatch.product_id == product_id)
    rows = db.execute(stmt.order_by(StockBatch.expiry_date.asc())).scalars().all()
    result = []
    today = date.today()
    for batch in rows:
        product = db.get(Product, batch.product_id)
        if product is None:
            continue
        remain = (batch.expiry_date - today).days
        if only_expiring and remain > max(1, int(product.shelf_life_days * 0.3)):
            continue
        result.append(
            {
                "id": batch.id,
                "batchNo": batch.batch_no,
                "productId": product.id,
                "productName": product.name,
                "qtyBase": batch.qty_base,
                "qtyText": units.humanize(db, product, batch.qty_base),
                "productionDate": batch.production_date.isoformat() if batch.production_date else None,
                "expiryDate": batch.expiry_date.isoformat(),
                "remainDays": remain,
                "expired": remain < 0,
            }
        )
    return ok(result)


@router.get("/movements", summary="库存流水")
def list_movements(
    store_id: int | None = None,
    product_id: int | None = None,
    movement_type: str = "",
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = _resolve_store(db, user, store_id)
    stmt = select(StockMovement).where(StockMovement.store_id == sid)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if movement_type:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    rows = db.execute(stmt.order_by(StockMovement.id.desc()).limit(min(limit, 500))).scalars().all()
    result = []
    for m in rows:
        product = db.get(Product, m.product_id)
        result.append(
            {
                "id": m.id,
                "productId": m.product_id,
                "productName": product.name if product else "",
                "type": m.movement_type,
                "qtyBase": m.qty_base,
                "qtyText": units.humanize(db, product, abs(m.qty_base)) if product else str(m.qty_base),
                "direction": "IN" if m.qty_base > 0 else "OUT",
                "refType": m.ref_type,
                "refNo": m.ref_no,
                "reasonCode": m.reason_code,
                "note": m.note,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
        )
    return ok(result)


@router.post("/receive", summary="收货入库（自动生成批次与效期）")
def receive(
    body: ReceiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.STORE_CLERK, Role.WAREHOUSE, Role.ADMIN)),
):
    ensure_store_access(db, user, body.store_id)
    movements = inv.receive(
        db,
        store_id=body.store_id,
        items=[i.model_dump() for i in body.items],
        ref_no=body.ref_no,
        batch_no=body.batch_no,
        production_date=body.production_date,
        operator_id=user.id,
    )
    db.commit()
    return ok({"count": len(movements)}, "入库成功")


@router.post("/outbound", summary="领用出库（FEFO）")
def outbound(
    body: OutboundIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.STORE_CLERK, Role.ADMIN)),
):
    ensure_store_access(db, user, body.store_id)
    movements = inv.outbound(
        db,
        store_id=body.store_id,
        items=[i.model_dump() for i in body.items],
        ref_type=body.ref_type,
        operator_id=user.id,
        note=body.note,
    )
    db.commit()
    return ok({"count": len(movements)}, "出库成功")


@router.post("/loss", summary="报损")
def report_loss(
    body: LossIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.STORE_CLERK, Role.ADMIN)),
):
    ensure_store_access(db, user, body.store_id)
    movements = inv.loss(
        db,
        store_id=body.store_id,
        items=[i.model_dump() for i in body.items],
        reason_code=body.reason_code,
        operator_id=user.id,
        note=body.note,
    )
    db.commit()
    return ok({"count": len(movements)}, "报损已登记")


@router.post("/stocktake", summary="创建盘点单")
def create_stocktake(
    store_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.ADMIN)),
):
    ensure_store_access(db, user, store_id)
    order = inv.create_stocktake(db, store_id, user.id)
    db.commit()
    items = db.execute(
        select(Stock, Product).join(Product, Product.id == Stock.product_id).where(Stock.store_id == store_id)
    ).all()
    return ok(
        {
            "id": order.id,
            "items": [
                {
                    "productId": p.id,
                    "productName": p.name,
                    "bookQtyBase": s.qty_base,
                    "bookQtyText": units.humanize(db, p, s.qty_base),
                }
                for s, p in items
            ],
        },
        "盘点单已创建",
    )


@router.post("/stocktake/{stocktake_id}/confirm", summary="确认盘点并调整库存")
def confirm_stocktake(
    stocktake_id: int,
    body: StocktakeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.ADMIN)),
):
    order = db.get(StocktakeOrder, stocktake_id)
    if order is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    ensure_store_access(db, user, order.store_id)
    movements = inv.confirm_stocktake(
        db, stocktake_id=stocktake_id, items=body.items, operator_id=user.id
    )
    db.commit()
    return ok({"adjusted": len(movements)}, "盘点完成，库存已调整")


@router.post("/transfer", summary="跨店调拨")
def transfer(
    body: TransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REGION_MANAGER, Role.HQ_PLANNER, Role.ADMIN)),
):
    ensure_store_access(db, user, body.from_store_id)
    order = inv.transfer(
        db,
        from_store_id=body.from_store_id,
        to_store_id=body.to_store_id,
        product_id=body.product_id,
        qty=body.qty,
        unit=body.unit,
        operator_id=user.id,
    )
    db.commit()
    return ok({"transferNo": order.transfer_no}, "调拨完成")


@router.get("/expiring", summary="临期/过期批次汇总")
def expiring(
    store_id: int | None = None,
    days: int = 3,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = _resolve_store(db, user, store_id)
    deadline = date.today() + timedelta(days=days)
    rows = (
        db.execute(
            select(StockBatch).where(
                StockBatch.store_id == sid,
                StockBatch.qty_base > 0,
                StockBatch.expiry_date <= deadline,
            ).order_by(StockBatch.expiry_date)
        )
        .scalars()
        .all()
    )
    result = []
    for batch in rows:
        product = db.get(Product, batch.product_id)
        if product is None:
            continue
        result.append(
            {
                "batchNo": batch.batch_no,
                "productName": product.name,
                "qtyText": units.humanize(db, product, batch.qty_base),
                "expiryDate": batch.expiry_date.isoformat(),
                "remainDays": (batch.expiry_date - date.today()).days,
            }
        )
    return ok(result)


@router.get("/stores-overview", summary="全域门店库存概览（总部视角）")
def stores_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scope = allowed_store_ids(db, user)
    stmt = select(Store).where(Store.is_active.is_(True))
    if scope is not None:
        stmt = stmt.where(Store.id.in_(scope or [-1]))
    stores = db.execute(stmt).scalars().all()
    result = []
    for store in stores:
        stocks = db.execute(select(Stock).where(Stock.store_id == store.id)).scalars().all()
        zero = sum(1 for s in stocks if (s.qty_base - s.locked_base) <= 0)
        result.append(
            {
                "storeId": store.id,
                "storeName": store.name,
                "skuCount": len(stocks),
                "zeroCount": zero,
            }
        )
    return ok(result)
