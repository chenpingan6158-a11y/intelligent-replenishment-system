"""订货单接口：创建、提交、审批、发货、收货、取消。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..database import get_db
from ..deps import allowed_store_ids, ensure_store_access, get_current_user, require_roles, user_store_id
from ..models import OrderStatus, PurchaseOrder, Role, User
from ..schemas import OrderActionIn, OrderCreateIn, ReceiveOrderIn
from ..services import ordering

router = APIRouter(prefix="/api/orders", tags=["订货"])

APPROVER_ROLES = (Role.REGION_MANAGER, Role.HQ_PLANNER, Role.ADMIN)


def _load(db: Session, order_id: int, user: User) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订货单不存在")
    ensure_store_access(db, user, order.store_id)
    return order


@router.get("", summary="订货单列表")
def list_orders(
    store_id: int | None = None,
    status: str = "",
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scope = allowed_store_ids(db, user)
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if store_id:
        ensure_store_access(db, user, store_id)
        stmt = stmt.where(PurchaseOrder.store_id == store_id)
    elif scope is not None:
        stmt = stmt.where(PurchaseOrder.store_id.in_(scope or [-1]))
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    rows = db.execute(stmt.limit(min(limit, 200))).scalars().all()
    return ok([ordering.summarize(o, db) for o in rows])


@router.get("/pending", summary="待我审批的订货单")
def pending(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in APPROVER_ROLES:
        return ok([])
    scope = allowed_store_ids(db, user)
    stmt = select(PurchaseOrder).where(PurchaseOrder.status == OrderStatus.SUBMITTED).order_by(PurchaseOrder.id)
    if scope is not None:
        stmt = stmt.where(PurchaseOrder.store_id.in_(scope or [-1]))
    rows = db.execute(stmt).scalars().all()
    return ok([ordering.summarize(o, db) for o in rows])


@router.post("", summary="创建订货单（草稿）")
def create_order(
    body: OrderCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.STORE_CLERK, Role.ADMIN)),
):
    ensure_store_access(db, user, body.store_id)
    order = ordering.create_order(
        db,
        store_id=body.store_id,
        items=[i.model_dump() for i in body.items],
        user=user,
        remark=body.remark,
    )
    db.commit()
    return ok(ordering.summarize(order, db), "订货单已创建")


@router.get("/{order_id}", summary="订货单详情")
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ok(ordering.summarize(_load(db, order_id, user), db))


@router.post("/{order_id}/submit", summary="提交订货单（命中免审规则则自动通过）")
def submit(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _load(db, order_id, user)
    order, auto, reasons = ordering.submit_order(db, order, user)
    db.commit()
    db.refresh(order)
    return ok(
        {
            "order": ordering.summarize(order, db),
            "autoApproved": auto,
            "approvalReasons": reasons,
        },
        "已自动通过审批" if auto else "已提交，等待审批",
    )


@router.post("/{order_id}/approve", summary="审批通过")
def approve(
    order_id: int,
    body: OrderActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*APPROVER_ROLES)),
):
    order = _load(db, order_id, user)
    ordering.approve_order(db, order, user, body.opinion)
    db.commit()
    return ok(ordering.summarize(order, db), "审批通过")


@router.post("/{order_id}/reject", summary="审批驳回")
def reject(
    order_id: int,
    body: OrderActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*APPROVER_ROLES)),
):
    order = _load(db, order_id, user)
    ordering.reject_order(db, order, user, body.opinion)
    db.commit()
    return ok(ordering.summarize(order, db), "已驳回")


@router.post("/{order_id}/confirm", summary="中央厨房发货（进入在途）")
def confirm(
    order_id: int,
    body: OrderActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.WAREHOUSE, Role.ADMIN)),
):
    order = _load(db, order_id, user)
    ordering.confirm_order(db, order, user, body.opinion)
    db.commit()
    return ok(ordering.summarize(order, db), "已发货")


@router.post("/{order_id}/receive", summary="门店收货（支持部分收货与差异登记）")
def receive(
    order_id: int,
    body: ReceiveOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.STORE_CLERK, Role.ADMIN)),
):
    order = _load(db, order_id, user)
    result = ordering.receive_order(db, order, user, body.items, body.opinion)
    db.commit()
    return ok(
        {
            "order": ordering.summarize(result["order"], db),
            "discrepancies": result["discrepancies"],
        },
        "收货完成" if not result["discrepancies"] else "收货完成，存在到货差异",
    )


@router.post("/{order_id}/cancel", summary="取消订单")
def cancel(order_id: int, body: OrderActionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = _load(db, order_id, user)
    ordering.cancel_order(db, order, user, body.opinion)
    db.commit()
    return ok(ordering.summarize(order, db), "订单已取消")


@router.post("/{order_id}/close", summary="归档订单")
def close(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    order = _load(db, order_id, user)
    ordering.close_order(db, order, user)
    db.commit()
    return ok(ordering.summarize(order, db), "订单已归档")
