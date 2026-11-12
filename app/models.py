"""领域模型。

设计约定（对应报告 BR-01）：
  * 所有数量字段均以「最小计量单位」（克 / 毫升 / 个）的整数存储，杜绝浮点误差；
  * 所有金额字段均以「分」的整数存储；
  * 展示层与订货层通过 unit_conversion 表换算。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


# --------------------------------------------------------------------------
# 角色与订单状态常量
# --------------------------------------------------------------------------
class Role:
    ADMIN = "ADMIN"            # 系统管理员
    HQ_PLANNER = "HQ_PLANNER"  # 总部供应链计划员
    REGION_MANAGER = "REGION_MANAGER"  # 区域经理
    STORE_MANAGER = "STORE_MANAGER"    # 门店店长
    STORE_CLERK = "STORE_CLERK"        # 门店员工
    WAREHOUSE = "WAREHOUSE"    # 中央厨房 / 中心仓


class OrderStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"   # 已发货，在途
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MovementType:
    IN = "IN"              # 采购/配送入库
    OUT = "OUT"            # 领用出库
    ADJUST = "ADJUST"      # 盘点调整
    LOSS = "LOSS"          # 报损
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class AlertType:
    LOW_STOCK = "LOW_STOCK"
    STOCKOUT_RISK = "STOCKOUT_RISK"
    NEAR_EXPIRY = "NEAR_EXPIRY"
    SLOW_MOVING = "SLOW_MOVING"


# --------------------------------------------------------------------------
# 组织
# --------------------------------------------------------------------------
class Region(Base):
    __tablename__ = "region"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(60), nullable=False)

    stores = relationship("Store", back_populates="region")


class Store(Base):
    __tablename__ = "store"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    region_id = Column(Integer, ForeignKey("region.id"), nullable=False, index=True)
    address = Column(String(200), default="")
    is_active = Column(Boolean, default=True, nullable=False)

    region = relationship("Region", back_populates="stores")


class User(Base):
    __tablename__ = "app_user"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(50), nullable=False, default="")
    role = Column(String(20), nullable=False, default=Role.STORE_MANAGER)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=True)
    region_id = Column(Integer, ForeignKey("region.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

    store = relationship("Store", foreign_keys=[store_id])
    region = relationship("Region", foreign_keys=[region_id])


# --------------------------------------------------------------------------
# 商品与配方
# --------------------------------------------------------------------------
class Category(Base):
    __tablename__ = "category"

    id = Column(Integer, primary_key=True)
    name = Column(String(40), unique=True, nullable=False)


class Product(Base):
    __tablename__ = "product"

    id = Column(Integer, primary_key=True)
    sku = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    category_id = Column(Integer, ForeignKey("category.id"), nullable=False)
    base_unit = Column(String(10), nullable=False, default="g")     # 克 / 毫升 / 个
    order_unit = Column(String(10), nullable=False, default="箱")   # 订货单位
    base_per_order_unit = Column(Integer, nullable=False, default=1)  # 1 订货单位 = N 最小单位
    shelf_life_days = Column(Integer, nullable=False, default=7)
    storage_type = Column(String(20), default="冷藏")               # 常温 / 冷藏 / 冷冻
    unit_price_cents = Column(Integer, nullable=False, default=0)   # 每订货单位单价（分）
    is_active = Column(Boolean, default=True, nullable=False)

    category = relationship("Category")


class UnitConversion(Base):
    """通用单位换算：1 from_unit = factor × to_unit（同一商品内）。"""

    __tablename__ = "unit_conversion"
    __table_args__ = (UniqueConstraint("product_id", "from_unit", "to_unit", name="uq_conv"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    from_unit = Column(String(10), nullable=False)
    to_unit = Column(String(10), nullable=False)
    factor = Column(Integer, nullable=False)


class Recipe(Base):
    """菜品（用于把销量折算成原料消耗）。"""

    __tablename__ = "recipe"

    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    price_cents = Column(Integer, default=0)

    items = relationship("RecipeItem", back_populates="recipe", cascade="all, delete-orphan")


class RecipeItem(Base):
    __tablename__ = "recipe_item"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipe.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    qty_base = Column(Integer, nullable=False)  # 每份用量（最小单位）

    recipe = relationship("Recipe", back_populates="items")
    product = relationship("Product")


# --------------------------------------------------------------------------
# 补货策略 / 库存
# --------------------------------------------------------------------------
class ReplenishmentPolicy(Base):
    __tablename__ = "replenishment_policy"
    __table_args__ = (UniqueConstraint("store_id", "product_id", name="uq_policy_store_product"),)

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    lead_time_days = Column(Integer, nullable=False, default=2)     # 提前期
    order_cycle_days = Column(Integer, nullable=False, default=3)   # 订货周期
    moq_base = Column(Integer, nullable=False, default=1)           # 最小起订量（最小单位）
    pack_multiple_base = Column(Integer, nullable=False, default=1) # 订货包装倍数（最小单位）
    max_stock_base = Column(Integer, nullable=False, default=0)     # 0 表示不限制
    service_level_z = Column(Integer, nullable=False, default=165)  # Z×100，165 表示 1.65
    is_enabled = Column(Boolean, default=True, nullable=False)

    product = relationship("Product")


class Stock(Base):
    """门店 + SKU 的库存汇总（以最小单位计）。version 用于乐观锁防超卖。"""

    __tablename__ = "stock"
    __table_args__ = (UniqueConstraint("store_id", "product_id", name="uq_stock_store_product"),)

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    qty_base = Column(Integer, nullable=False, default=0)      # 现存
    locked_base = Column(Integer, nullable=False, default=0)   # 锁定（已下单未到货不锁库存，此处用于出库占用）
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=now, onupdate=now)

    product = relationship("Product")


class StockBatch(Base):
    """批次库存：FEFO 依据。"""

    __tablename__ = "stock_batch"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    batch_no = Column(String(40), nullable=False)
    production_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=False, index=True)
    qty_base = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=now, nullable=False)

    product = relationship("Product")


class StockMovement(Base):
    """库存流水：一切库存变动的唯一凭证（BR-04）。"""

    __tablename__ = "stock_movement"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("stock_batch.id"), nullable=True)
    movement_type = Column(String(20), nullable=False, index=True)
    qty_base = Column(Integer, nullable=False)          # 正数入库、负数出库
    unit_cost_cents = Column(Integer, default=0)
    ref_type = Column(String(20), default="")           # PURCHASE_ORDER / STOCKTAKE / LOSS / TRANSFER
    ref_no = Column(String(40), default="", index=True)
    reason_code = Column(String(20), default="")        # EXPIRED / DAMAGED / PROCESS_LOSS ...
    operator_id = Column(Integer, ForeignKey("app_user.id"), nullable=True)
    note = Column(String(200), default="")
    created_at = Column(DateTime, default=now, nullable=False, index=True)


class StocktakeOrder(Base):
    """盘点单。"""

    __tablename__ = "stocktake_order"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False)
    status = Column(String(20), default="DRAFT", nullable=False)  # DRAFT / CONFIRMED
    created_by = Column(Integer, ForeignKey("app_user.id"))
    created_at = Column(DateTime, default=now, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)


class StocktakeItem(Base):
    __tablename__ = "stocktake_item"

    id = Column(Integer, primary_key=True)
    stocktake_id = Column(Integer, ForeignKey("stocktake_order.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    book_qty_base = Column(Integer, nullable=False, default=0)
    actual_qty_base = Column(Integer, nullable=False, default=0)

    product = relationship("Product")


# --------------------------------------------------------------------------
# 消耗数据
# --------------------------------------------------------------------------
class SalesDaily(Base):
    __tablename__ = "sales_daily"
    __table_args__ = (UniqueConstraint("store_id", "biz_date", "recipe_id", name="uq_sales"),)

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    biz_date = Column(Date, nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipe.id"), nullable=False)
    qty = Column(Integer, nullable=False, default=0)


class ConsumptionDaily(Base):
    """原料日消耗（由销量 × 配方折算，或由出库汇总）。"""

    __tablename__ = "consumption_daily"
    __table_args__ = (UniqueConstraint("store_id", "biz_date", "product_id", name="uq_consumption"),)

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    biz_date = Column(Date, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    qty_base = Column(Integer, nullable=False, default=0)


# --------------------------------------------------------------------------
# 订货与审批
# --------------------------------------------------------------------------
class PurchaseOrder(Base):
    __tablename__ = "purchase_order"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(30), unique=True, nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default=OrderStatus.DRAFT, index=True)
    total_cents = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("app_user.id"), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    expected_delivery_date = Column(Date, nullable=True)
    remark = Column(String(200), default="")
    version = Column(Integer, nullable=False, default=0)

    store = relationship("Store")
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")
    approvals = relationship("ApprovalRecord", back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_item"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    suggest_qty_base = Column(Integer, nullable=False, default=0)
    order_qty_base = Column(Integer, nullable=False, default=0)
    received_qty_base = Column(Integer, nullable=False, default=0)
    unit_price_cents = Column(Integer, nullable=False, default=0)
    amount_cents = Column(Integer, nullable=False, default=0)
    adjust_reason = Column(String(200), default="")

    order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")


class ApprovalRecord(Base):
    __tablename__ = "approval_record"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("purchase_order.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False)   # SUBMIT / APPROVE / REJECT / CONFIRM / RECEIVE / CANCEL
    operator_id = Column(Integer, ForeignKey("app_user.id"))
    opinion = Column(String(200), default="")
    created_at = Column(DateTime, default=now, nullable=False)

    order = relationship("PurchaseOrder", back_populates="approvals")


class TransferOrder(Base):
    """跨店调拨单。"""

    __tablename__ = "transfer_order"

    id = Column(Integer, primary_key=True)
    transfer_no = Column(String(30), unique=True, nullable=False)
    from_store_id = Column(Integer, ForeignKey("store.id"), nullable=False)
    to_store_id = Column(Integer, ForeignKey("store.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    qty_base = Column(Integer, nullable=False)
    status = Column(String(20), default="DONE", nullable=False)
    created_by = Column(Integer, ForeignKey("app_user.id"))
    created_at = Column(DateTime, default=now, nullable=False)


# --------------------------------------------------------------------------
# 预警 / 日志
# --------------------------------------------------------------------------
class Alert(Base):
    __tablename__ = "alert"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    alert_type = Column(String(20), nullable=False, index=True)
    level = Column(String(10), nullable=False, default="WARN")   # INFO / WARN / CRITICAL
    message = Column(String(200), nullable=False, default="")
    status = Column(String(20), nullable=False, default="OPEN", index=True)  # OPEN / HANDLED / IGNORED
    created_at = Column(DateTime, default=now, nullable=False, index=True)
    handled_by = Column(Integer, ForeignKey("app_user.id"), nullable=True)
    handled_at = Column(DateTime, nullable=True)


class OperationLog(Base):
    __tablename__ = "operation_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=True)
    username = Column(String(50), default="")
    action = Column(String(60), nullable=False)
    target = Column(String(60), default="")
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=now, nullable=False, index=True)


Index("ix_movement_store_product_date", StockMovement.store_id, StockMovement.product_id, StockMovement.created_at)
Index("ix_consumption_store_date", ConsumptionDaily.store_id, ConsumptionDaily.biz_date)
