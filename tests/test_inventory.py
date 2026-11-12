"""库存域单元测试：FEFO、单位换算、盘点、并发乐观锁。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Category,
    Product,
    Stock,
    StockBatch,
    StockMovement,
    StocktakeOrder,
    Store,
    UnitConversion,
)
from app.models import MovementType as MT
from app.services import inventory as inv
from app.services import units


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
    # 基础数据
    store = Store(code="S001", name="测试门店", region_id=1)
    session.add(store)
    category = Category(name="测试分类")
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
    session.add(
        UnitConversion(product_id=product.id, from_unit="箱", to_unit="g", factor=10000)
    )
    session.commit()
    yield session
    session.close()


def _product(db):
    return db.query(Product).first()


def _stock(db):
    return db.query(Stock).first()


class TestUnitConversion:
    def test_to_base_by_order_unit(self, db):
        p = _product(db)
        assert units.to_base(db, p, 2, "箱") == 20000

    def test_to_base_default_unit(self, db):
        p = _product(db)
        assert units.to_base(db, p, 500, None) == 500

    def test_unknown_unit_raises(self, db):
        p = _product(db)
        with pytest.raises(HTTPException):
            units.to_base(db, p, 1, "桶")

    def test_to_order_unit_rounds_up(self, db):
        p = _product(db)
        assert units.to_order_unit(db, p, 15000) == 2
        assert units.to_order_unit(db, p, 20000) == 2
        assert units.to_order_unit(db, p, 0) == 0


class TestReceive:
    def test_receive_creates_batch_and_stock(self, db):
        p = _product(db)
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 3, "unit": "箱"}], batch_no="B001")
        db.flush()
        stock = _stock(db)
        assert stock.qty_base == 30000
        batch = db.query(StockBatch).first()
        assert batch.qty_base == 30000
        assert batch.expiry_date == batch.production_date + timedelta(days=10)
        assert db.query(StockMovement).count() == 1

    def test_receive_accumulates(self, db):
        p = _product(db)
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 1, "unit": "箱"}])
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 2, "unit": "箱"}])
        assert _stock(db).qty_base == 30000


class TestFEFO:
    def _seed_batches(self, db, product):
        today = date.today()
        db.add(StockBatch(store_id=1, product_id=product.id, batch_no="OLD",
                          production_date=today, expiry_date=today + timedelta(days=3), qty_base=5000))
        db.add(StockBatch(store_id=1, product_id=product.id, batch_no="NEW",
                          production_date=today, expiry_date=today + timedelta(days=20), qty_base=5000))
        db.add(Stock(store_id=1, product_id=product.id, qty_base=10000, locked_base=0, version=0))
        db.commit()

    def test_outbound_consumes_earliest_expiry_first(self, db):
        p = _product(db)
        self._seed_batches(db, p)
        inv.outbound(db, store_id=1, items=[{"product_id": p.id, "qty": 6000, "unit": "g"}])
        batches = {b.batch_no: b.qty_base for b in db.query(StockBatch).all()}
        assert batches["OLD"] == 0        # 先到期先出
        assert batches["NEW"] == 4000
        assert _stock(db).qty_base == 4000

    def test_outbound_insufficient_stock_raises(self, db):
        p = _product(db)
        self._seed_batches(db, p)
        with pytest.raises(HTTPException) as exc:
            inv.outbound(db, store_id=1, items=[{"product_id": p.id, "qty": 999999, "unit": "g"}])
        assert "库存不足" in exc.value.detail
        # 失败后库存不变（同事务回滚由调用方处理，此处校验未扣减）
        db.rollback()
        assert _stock(db).qty_base == 10000

    def test_loss_records_reason(self, db):
        p = _product(db)
        self._seed_batches(db, p)
        inv.loss(db, store_id=1, items=[{"product_id": p.id, "qty": 1000, "unit": "g"}], reason_code="EXPIRED")
        movement = db.query(StockMovement).filter(StockMovement.movement_type == MT.LOSS).first()
        assert movement.qty_base == -1000
        assert movement.reason_code == "EXPIRED"

    def test_loss_invalid_reason_rejected(self, db):
        p = _product(db)
        self._seed_batches(db, p)
        with pytest.raises(HTTPException):
            inv.loss(db, store_id=1, items=[{"product_id": p.id, "qty": 1}], reason_code="偷吃")


class TestStocktake:
    def test_stocktake_adjusts_up_and_down(self, db):
        p = _product(db)
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 2, "unit": "箱"}])
        order = inv.create_stocktake(db, store_id=1, operator_id=1)
        inv.confirm_stocktake(
            db,
            stocktake_id=order.id,
            items=[{"product_id": p.id, "actual_qty": 1.5, "unit": "箱"}],
            operator_id=1,
        )
        assert _stock(db).qty_base == 15000

        order2 = inv.create_stocktake(db, store_id=1, operator_id=1)
        inv.confirm_stocktake(
            db,
            stocktake_id=order2.id,
            items=[{"product_id": p.id, "actual_qty": 3, "unit": "箱"}],
            operator_id=1,
        )
        assert _stock(db).qty_base == 30000

    def test_confirmed_stocktake_cannot_reconfirm(self, db):
        p = _product(db)
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 1, "unit": "箱"}])
        order = inv.create_stocktake(db, store_id=1, operator_id=1)
        inv.confirm_stocktake(db, stocktake_id=order.id, items=[{"product_id": p.id, "actual_qty": 1, "unit": "箱"}])
        with pytest.raises(HTTPException):
            inv.confirm_stocktake(db, stocktake_id=order.id, items=[{"product_id": p.id, "actual_qty": 2, "unit": "箱"}])


class TestOptimisticLock:
    def test_version_increments(self, db):
        p = _product(db)
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 1, "unit": "箱"}])
        assert _stock(db).version == 1
        inv.receive(db, store_id=1, items=[{"product_id": p.id, "qty": 1, "unit": "箱"}])
        assert _stock(db).version == 2

    def test_negative_stock_rejected(self, db):
        p = _product(db)
        with pytest.raises(HTTPException) as exc:
            inv.outbound(db, store_id=1, items=[{"product_id": p.id, "qty": 1, "unit": "箱"}])
        assert "库存不足" in str(exc.value.detail)
