"""请求体模型（Pydantic v2）。响应统一走 {code, message, data} 信封。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ 认证
class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=64)
    full_name: str = Field(min_length=1, max_length=50)
    role: str
    store_id: int | None = None
    region_id: int | None = None


class UserStatusIn(BaseModel):
    is_active: bool


# ------------------------------------------------------------------ 主数据
class RegionIn(BaseModel):
    code: str
    name: str


class StoreIn(BaseModel):
    code: str
    name: str
    region_id: int
    address: str = ""
    is_active: bool = True


class CategoryIn(BaseModel):
    name: str


class ProductIn(BaseModel):
    sku: str
    name: str
    category_id: int
    base_unit: str = "g"
    order_unit: str = "箱"
    base_per_order_unit: int = Field(default=1, gt=0)
    shelf_life_days: int = Field(default=7, ge=0)
    storage_type: str = "冷藏"
    unit_price_cents: int = Field(default=0, ge=0)
    is_active: bool = True


class PolicyIn(BaseModel):
    store_id: int
    product_id: int
    lead_time_days: int = Field(default=2, ge=0)
    order_cycle_days: int = Field(default=3, ge=1)
    moq_base: int = Field(default=1, ge=0)
    pack_multiple_base: int = Field(default=1, ge=1)
    max_stock_base: int = Field(default=0, ge=0)
    service_level_z: int = Field(default=165, ge=0)
    is_enabled: bool = True


class RecipeItemIn(BaseModel):
    product_id: int
    qty_base: int = Field(gt=0)


class RecipeIn(BaseModel):
    code: str
    name: str
    price_cents: int = 0
    items: list[RecipeItemIn] = []


# ------------------------------------------------------------------ 库存
class LineQty(BaseModel):
    product_id: int
    qty: float = Field(gt=0)  # 支持小数录入（如 1.5 箱），换算后按最小单位取整
    unit: str | None = None  # 不传则按最小单位


class ReceiveIn(BaseModel):
    store_id: int
    items: list[LineQty]
    ref_no: str = ""
    batch_no: str = ""
    production_date: date | None = None


class OutboundIn(BaseModel):
    store_id: int
    items: list[LineQty]
    ref_type: str = "OUT"
    note: str = ""


class LossIn(BaseModel):
    store_id: int
    items: list[LineQty]
    reason_code: str = "EXPIRED"  # EXPIRED / DAMAGED / PROCESS_LOSS / OTHER
    note: str = ""


class StocktakeIn(BaseModel):
    store_id: int
    items: list[dict]  # [{"product_id":1,"actual_qty":12,"unit":"瓶"}]
    note: str = ""


class TransferIn(BaseModel):
    from_store_id: int
    to_store_id: int
    product_id: int
    qty: int = Field(gt=0)
    unit: str | None = None


# ------------------------------------------------------------------ 订货
class OrderItemIn(BaseModel):
    product_id: int
    order_qty: int = Field(gt=0)          # 以订货单位计
    suggest_qty: int = 0                  # 以订货单位计（用于偏离度计算）
    adjust_reason: str = ""


class OrderCreateIn(BaseModel):
    store_id: int
    items: list[OrderItemIn]
    remark: str = ""


class OrderActionIn(BaseModel):
    opinion: str = ""


class ReceiveOrderIn(BaseModel):
    items: list[dict] = []  # [{"product_id":1,"received_qty":9}] 单位=订货单位；空表示按订单量整单收货
    opinion: str = ""


# ------------------------------------------------------------------ 预警
class AlertHandleIn(BaseModel):
    action: str = "HANDLE"  # HANDLE / IGNORE
    note: str = ""


# ------------------------------------------------------------------ 销售导入
class SalesRowIn(BaseModel):
    store_id: int
    biz_date: date
    recipe_id: int
    qty: int = Field(ge=0)


class SalesImportIn(BaseModel):
    rows: list[SalesRowIn]
