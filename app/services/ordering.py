"""订货流程服务：状态机 + 审批规则 + 收货差异处理。"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APPROVAL_AMOUNT_THRESHOLD_CENTS, APPROVAL_DEVIATION_RATIO
from ..models import (
    ApprovalRecord,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    ReplenishmentPolicy,
    Store,
    User,
)
from . import inventory, units

# 状态机：当前状态 -> 允许的下一状态
TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.DRAFT: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.APPROVED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.APPROVED: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.REJECTED: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.RECEIVED, OrderStatus.CLOSED},
    OrderStatus.RECEIVED: {OrderStatus.CLOSED},
    OrderStatus.CLOSED: set(),
    OrderStatus.CANCELLED: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def _assert_transition(order: PurchaseOrder, target: str) -> None:
    if not can_transition(order.status, target):
        raise HTTPException(
            status_code=400,
            detail=f"非法的状态流转：{order.status} → {target}",
        )


def _gen_order_no(db: Session) -> str:
    prefix = f"PO{date.today():%Y%m%d}"
    for _ in range(20):
        candidate = f"{prefix}{secrets.randbelow(9000) + 1000}"
        exists = db.execute(select(PurchaseOrder.id).where(PurchaseOrder.order_no == candidate)).first()
        if not exists:
            return candidate
    raise HTTPException(status_code=500, detail="订单号生成失败，请重试")


def _deviation_ratio(items: list[PurchaseOrderItem]) -> float:
    worst = 0.0
    for item in items:
        if item.suggest_qty_base and item.suggest_qty_base > 0:
            worst = max(worst, abs(item.order_qty_base - item.suggest_qty_base) / item.suggest_qty_base)
    return worst


def requires_approval(db: Session, store_id: int, items: list[PurchaseOrderItem], total_cents: int) -> tuple[bool, list[str]]:
    """BR-07：金额超阈值 / 偏离建议量超阈值 / 超最大库存，任一命中即需审批。"""
    reasons: list[str] = []
    if total_cents > APPROVAL_AMOUNT_THRESHOLD_CENTS:
        reasons.append(f"订单金额 {total_cents / 100:.2f} 元超过 {APPROVAL_AMOUNT_THRESHOLD_CENTS / 100:.0f} 元阈值")

    deviation = _deviation_ratio(items)
    if deviation > APPROVAL_DEVIATION_RATIO:
        reasons.append(f"订货量偏离建议量 {deviation * 100:.0f}%，超过 {APPROVAL_DEVIATION_RATIO * 100:.0f}% 阈值")

    for item in items:
        policy = db.execute(
            select(ReplenishmentPolicy).where(
                ReplenishmentPolicy.store_id == store_id,
                ReplenishmentPolicy.product_id == item.product_id,
            )
        ).scalar_one_or_none()
        if policy and policy.max_stock_base > 0 and item.order_qty_base > policy.max_stock_base:
            reasons.append(f"商品 {item.product_id} 订货量超过最大库存约束")
            break

    return bool(reasons), reasons


# ------------------------------------------------------------------ 创建与提交
def create_order(db: Session, *, store_id: int, items: list[dict], user: User, remark: str = "") -> PurchaseOrder:
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="门店不存在")
    if not items:
        raise HTTPException(status_code=400, detail="订货单不能为空")
    if db.execute(
        select(PurchaseOrder.id).where(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status == OrderStatus.DRAFT,
        )
    ).first():
        # 草稿可并存，这里仅提示不阻断
        pass

    order = PurchaseOrder(
        order_no=_gen_order_no(db),
        store_id=store_id,
        status=OrderStatus.DRAFT,
        created_by=user.id,
        remark=remark,
        expected_delivery_date=date.today() + timedelta(days=2),
    )
    db.add(order)
    db.flush()

    total = 0
    for item in items:
        product = db.get(Product, item["product_id"])
        if product is None:
            raise HTTPException(status_code=404, detail=f"商品 {item['product_id']} 不存在")
        qty_order = int(item["order_qty"])
        qty_base = qty_order * units.base_per_order(product)
        amount = qty_order * product.unit_price_cents
        total += amount
        db.add(
            PurchaseOrderItem(
                order_id=order.id,
                product_id=product.id,
                suggest_qty_base=int(item.get("suggest_qty", 0)) * units.base_per_order(product),
                order_qty_base=qty_base,
                unit_price_cents=product.unit_price_cents,
                amount_cents=amount,
                adjust_reason=item.get("adjust_reason", ""),
            )
        )
    order.total_cents = total
    db.flush()
    db.refresh(order)
    return order


def submit_order(db: Session, order: PurchaseOrder, user: User) -> tuple[PurchaseOrder, bool, list[str]]:
    _assert_transition(order, OrderStatus.SUBMITTED)
    need, reasons = requires_approval(db, order.store_id, order.items, order.total_cents)
    order.status = OrderStatus.SUBMITTED
    order.submitted_at = __import__("datetime").datetime.now().replace(microsecond=0)
    db.add(ApprovalRecord(order_id=order.id, action="SUBMIT", operator_id=user.id, opinion="提交订货单"))

    auto_approved = False
    if not need:
        # 免审单：自动通过，减少店长等待
        order.status = OrderStatus.APPROVED
        db.add(
            ApprovalRecord(
                order_id=order.id,
                action="APPROVE",
                operator_id=None,
                opinion="命中免审规则，系统自动通过",
            )
        )
        auto_approved = True
    db.flush()
    return order, auto_approved, reasons


def approve_order(db: Session, order: PurchaseOrder, user: User, opinion: str = "") -> PurchaseOrder:
    _assert_transition(order, OrderStatus.APPROVED)
    order.status = OrderStatus.APPROVED
    db.add(ApprovalRecord(order_id=order.id, action="APPROVE", operator_id=user.id, opinion=opinion or "审批通过"))
    db.flush()
    return order


def reject_order(db: Session, order: PurchaseOrder, user: User, opinion: str = "") -> PurchaseOrder:
    _assert_transition(order, OrderStatus.REJECTED)
    order.status = OrderStatus.REJECTED
    db.add(ApprovalRecord(order_id=order.id, action="REJECT", operator_id=user.id, opinion=opinion or "审批驳回"))
    db.flush()
    return order


def confirm_order(db: Session, order: PurchaseOrder, user: User, opinion: str = "") -> PurchaseOrder:
    """中央厨房发货，订单进入在途。"""
    _assert_transition(order, OrderStatus.CONFIRMED)
    order.status = OrderStatus.CONFIRMED
    db.add(ApprovalRecord(order_id=order.id, action="CONFIRM", operator_id=user.id, opinion=opinion or "已发货"))
    db.flush()
    return order


def cancel_order(db: Session, order: PurchaseOrder, user: User, opinion: str = "") -> PurchaseOrder:
    _assert_transition(order, OrderStatus.CANCELLED)
    order.status = OrderStatus.CANCELLED
    db.add(ApprovalRecord(order_id=order.id, action="CANCEL", operator_id=user.id, opinion=opinion or "取消订单"))
    db.flush()
    return order


def receive_order(
    db: Session,
    order: PurchaseOrder,
    user: User,
    received: list[dict] | None = None,
    opinion: str = "",
) -> dict:
    """BR-08：按实收入库，差异写回订单项并标记。"""
    _assert_transition(order, OrderStatus.RECEIVED)
    actual: dict[int, int] = {}
    for row in received or []:
        actual[int(row["product_id"])] = int(row["received_qty"])

    discrepancies = []
    for item in order.items:
        product = db.get(Product, item.product_id)
        assert product is not None
        ordered_order_unit = item.order_qty_base // units.base_per_order(product)
        recv_order_unit = actual.get(item.product_id, ordered_order_unit)
        if recv_order_unit < 0:
            raise HTTPException(status_code=400, detail="实收数量不能为负")
        recv_base = recv_order_unit * units.base_per_order(product)
        item.received_qty_base = recv_base
        if recv_base > 0:
            inventory.receive(
                db,
                store_id=order.store_id,
                items=[{"product_id": product.id, "qty": recv_base, "unit": product.base_unit}],
                ref_no=order.order_no,
                operator_id=user.id,
                note=f"订货单 {order.order_no} 收货",
            )
        if recv_base != item.order_qty_base:
            diff = recv_base - item.order_qty_base
            discrepancies.append(
                {
                    "productId": product.id,
                    "productName": product.name,
                    "orderedText": units.humanize(db, product, item.order_qty_base),
                    "receivedText": units.humanize(db, product, recv_base),
                    "diffBase": diff,
                    "diffText": units.humanize(db, product, abs(diff)),
                }
            )

    order.status = OrderStatus.RECEIVED
    note = opinion or ("全部收货" if not discrepancies else f"存在 {len(discrepancies)} 项到货差异")
    db.add(ApprovalRecord(order_id=order.id, action="RECEIVE", operator_id=user.id, opinion=note))
    db.flush()
    return {"order": order, "discrepancies": discrepancies}


def close_order(db: Session, order: PurchaseOrder, user: User) -> PurchaseOrder:
    _assert_transition(order, OrderStatus.CLOSED)
    order.status = OrderStatus.CLOSED
    db.add(ApprovalRecord(order_id=order.id, action="CLOSE", operator_id=user.id, opinion="订单归档"))
    db.flush()
    return order


def summarize(order: PurchaseOrder, db: Session) -> dict:
    store = db.get(Store, order.store_id)
    items = []
    for item in order.items:
        product = db.get(Product, item.product_id)
        assert product is not None
        items.append(
            {
                "productId": product.id,
                "sku": product.sku,
                "productName": product.name,
                "orderUnit": product.order_unit,
                "orderQty": item.order_qty_base // units.base_per_order(product),
                "suggestQty": item.suggest_qty_base // units.base_per_order(product),
                "receivedQty": item.received_qty_base // units.base_per_order(product),
                "unitPriceCents": item.unit_price_cents,
                "amountCents": item.amount_cents,
                "adjustReason": item.adjust_reason,
                "diffQty": (item.received_qty_base - item.order_qty_base) // units.base_per_order(product),
            }
        )
    return {
        "id": order.id,
        "orderNo": order.order_no,
        "storeId": order.store_id,
        "storeName": store.name if store else "",
        "status": order.status,
        "totalCents": order.total_cents,
        "createdAt": order.created_at.isoformat() if order.created_at else None,
        "submittedAt": order.submitted_at.isoformat() if order.submitted_at else None,
        "expectedDeliveryDate": order.expected_delivery_date.isoformat() if order.expected_delivery_date else None,
        "remark": order.remark,
        "items": items,
        "approvals": [
            {
                "action": a.action,
                "operatorId": a.operator_id,
                "opinion": a.opinion,
                "createdAt": a.created_at.isoformat() if a.created_at else None,
            }
            for a in sorted(order.approvals, key=lambda x: x.id)
        ],
    }
