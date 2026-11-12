"""订货流程单元测试：状态机、审批规则、收货差异。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Category,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Region,
    Role,
    Stock,
    StockBatch,
    StockMovement,
    Store,
    UnitConversion,
    User,
)
from app.models import OrderStatus as OS
from app.services import ordering


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    region = Region(code="R01", name="华东")
    session.add(region)
    session.flush()
    store = Store(code="S001", name="测试门店", region_id=region.id)
    session.add(store)
    session.flush()
    manager = User(username="sm001", password_hash="x", full_name="店长", role=Role.STORE_MANAGER, store_id=store.id)
    region_mgr = User(username="rm", password_hash="x", full_name="区域经理", role=Role.REGION_MANAGER, region_id=region.id)
    session.add_all([manager, region_mgr])
    category = Category(name="分类")
    session.add(category)
    session.flush()
    product = Product(
        sku="SKU0001",
        name="五花肉",
        category_id=category.id,
        base_unit="g",
        order_unit="箱",
        base_per_order_unit=10000,
        shelf_life_days=10,
        unit_price_cents=38000,
    )
    session.add(product)
    session.flush()
    session.add(UnitConversion(product_id=product.id, from_unit="箱", to_unit="g", factor=10000))
    session.commit()
    yield session
    session.close()


def _user(db, role=Role.STORE_MANAGER):
    return db.query(User).filter(User.role == role).first()


def _make_order(db, qty_boxes=1, suggest_boxes=1):
    user = _user(db)
    product = db.query(Product).first()
    order = ordering.create_order(
        db,
        store_id=1,
        items=[{"product_id": product.id, "order_qty": qty_boxes, "suggest_qty": suggest_boxes, "adjust_reason": ""}],
        user=user,
    )
    return order, product


class TestStateMachine:
    def test_valid_full_flow(self, db):
        order, _ = _make_order(db)
        assert order.status == OS.DRAFT
        ordering.submit_order(db, order, _user(db))
        if order.status == OS.SUBMITTED:  # 命中免审规则时已自动通过
            ordering.approve_order(db, order, _user(db, Role.REGION_MANAGER))
        ordering.confirm_order(db, order, _user(db, Role.WAREHOUSE) or _user(db))
        ordering.receive_order(db, order, _user(db))
        ordering.close_order(db, order, _user(db, Role.ADMIN) or _user(db))
        assert order.status == OS.CLOSED

    def test_invalid_transition_rejected(self, db):
        order, _ = _make_order(db)
        with pytest.raises(HTTPException) as exc:
            ordering.confirm_order(db, order, _user(db))  # DRAFT 不能直接发货
        assert "非法的状态流转" in exc.value.detail

    def test_cannot_receive_before_ship(self, db):
        order, _ = _make_order(db)
        ordering.submit_order(db, order, _user(db))
        with pytest.raises(HTTPException):
            ordering.receive_order(db, order, _user(db))

    def test_rejected_can_resubmit(self, db):
        order, _ = _make_order(db, qty_boxes=5)  # 金额超阈值，需人工审批
        ordering.submit_order(db, order, _user(db))
        assert order.status == OS.SUBMITTED
        ordering.reject_order(db, order, _user(db, Role.REGION_MANAGER), opinion="超预算")
        assert order.status == OS.REJECTED
        ordering.submit_order(db, order, _user(db))
        assert order.status in (OS.SUBMITTED, OS.APPROVED)


class TestApprovalRules:
    def test_large_amount_requires_approval(self, db):
        order, _ = _make_order(db, qty_boxes=2)  # 2 × 380 元 > 500 元
        _, auto, reasons = ordering.submit_order(db, order, _user(db))
        assert auto is False
        assert order.status == OS.SUBMITTED
        assert any("金额" in r for r in reasons)

    def test_small_order_auto_approved(self, db):
        # 把单价调低，使金额不超过阈值且无偏离
        product = db.query(Product).first()
        product.unit_price_cents = 10000  # 1 箱 100 元
        order, _ = _make_order(db, qty_boxes=1, suggest_boxes=1)
        _, auto, reasons = ordering.submit_order(db, order, _user(db))
        assert auto is True
        assert order.status == OS.APPROVED
        assert reasons == []

    def test_deviation_requires_approval(self, db):
        product = db.query(Product).first()
        product.unit_price_cents = 10000
        # 订 3 箱、建议 1 箱 → 偏离 200%
        order, _ = _make_order(db, qty_boxes=3, suggest_boxes=1)
        _, auto, reasons = ordering.submit_order(db, order, _user(db))
        assert auto is False
        assert any("偏离" in r for r in reasons)

    def test_max_stock_requires_approval(self, db):
        from app.models import ReplenishmentPolicy

        product = db.query(Product).first()
        product.unit_price_cents = 10000
        db.add(ReplenishmentPolicy(store_id=1, product_id=product.id, max_stock_base=2 * 10000))
        db.commit()
        order, _ = _make_order(db, qty_boxes=3, suggest_boxes=3)
        _, auto, reasons = ordering.submit_order(db, order, _user(db))
        assert auto is False
        assert any("最大库存" in r for r in reasons)


class TestReceive:
    def _approved_shipped_order(self, db, qty_boxes=2):
        order, _ = _make_order(db, qty_boxes=qty_boxes)
        ordering.submit_order(db, order, _user(db))
        if order.status == OS.SUBMITTED:
            ordering.approve_order(db, order, _user(db, Role.REGION_MANAGER))
        warehouse = _user(db, Role.WAREHOUSE) or _user(db)
        ordering.confirm_order(db, order, warehouse)
        return order

    def test_full_receive_updates_inventory(self, db):
        order = self._approved_shipped_order(db)
        result = ordering.receive_order(db, order, _user(db))
        assert result["discrepancies"] == []
        assert order.status == OS.RECEIVED
        stock = db.query(Stock).first()
        assert stock.qty_base == 20000
        movement = db.query(StockMovement).first()
        assert movement.qty_base == 20000

    def test_partial_receive_records_discrepancy(self, db):
        order = self._approved_shipped_order(db, qty_boxes=2)
        result = ordering.receive_order(db, order, _user(db), received=[{"product_id": 1, "received_qty": 1}])
        assert len(result["discrepancies"]) == 1
        diff = result["discrepancies"][0]
        assert diff["diffBase"] == -10000
        stock = db.query(Stock).first()
        assert stock.qty_base == 10000  # 按实收入库

    def test_receive_twice_rejected(self, db):
        order = self._approved_shipped_order(db)
        ordering.receive_order(db, order, _user(db))
        with pytest.raises(HTTPException):
            ordering.receive_order(db, order, _user(db))


class TestCreateOrder:
    def test_amount_calculated_correctly(self, db):
        order, _ = _make_order(db, qty_boxes=2)
        assert order.total_cents == 2 * 38000

    def test_empty_order_rejected(self, db):
        with pytest.raises(HTTPException):
            ordering.create_order(db, store_id=1, items=[], user=_user(db))

    def test_suggest_qty_recorded_in_order_units(self, db):
        order, _ = _make_order(db, qty_boxes=2, suggest_boxes=5)
        item = db.query(PurchaseOrderItem).first()
        assert item.order_qty_base == 20000
        assert item.suggest_qty_base == 50000
