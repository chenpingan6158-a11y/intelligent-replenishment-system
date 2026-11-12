"""单位换算（BR-01）。

系统内部一律使用「最小计量单位」的整数；仅在展示与订货录入时换算。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, UnitConversion


def get_factor(db: Session, product: Product, from_unit: str, to_unit: str) -> int:
    """返回 1 from_unit = factor × to_unit；未知换算抛 400。"""
    if from_unit == to_unit:
        return 1
    # 正向：from -> to
    row = db.execute(
        select(UnitConversion).where(
            UnitConversion.product_id == product.id,
            UnitConversion.from_unit == from_unit,
            UnitConversion.to_unit == to_unit,
        )
    ).scalar_one_or_none()
    if row:
        return row.factor
    # 反向：to -> from 取倒数前先校验整除
    rev = db.execute(
        select(UnitConversion).where(
            UnitConversion.product_id == product.id,
            UnitConversion.from_unit == to_unit,
            UnitConversion.to_unit == from_unit,
        )
    ).scalar_one_or_none()
    if rev and rev.factor > 0:
        return max(1, product.base_per_order_unit // rev.factor)
    raise HTTPException(status_code=400, detail=f"商品 {product.sku} 不支持 {from_unit} → {to_unit} 的换算")


def to_base(db: Session, product: Product, qty: int | float, unit: str | None = None) -> int:
    """把任意单位的数量换算为最小单位整数。

    支持小数录入（如 1.5 箱），四舍五入到最小单位。
    """
    qty = float(qty)
    if unit is None or unit == "" or unit == product.base_unit:
        return int(round(qty))
    return int(round(qty * get_factor(db, product, unit, product.base_unit)))


def to_order_unit(db: Session, product: Product, qty_base: int) -> int:
    """最小单位 → 订货单位的向上取整数量（用于展示与下单）。"""
    factor = product.base_per_order_unit or 1
    if qty_base <= 0:
        return 0
    return (qty_base + factor - 1) // factor


def base_per_order(product: Product) -> int:
    return product.base_per_order_unit or 1


def humanize(db: Session, product: Product, qty_base: int) -> str:
    """把最小单位数量渲染成人类可读串，如 12500g → 1箱 500g。"""
    factor = base_per_order(product)
    if factor <= 1:
        return f"{qty_base}{product.base_unit}"
    boxes, rest = divmod(qty_base, factor)
    parts = []
    if boxes:
        parts.append(f"{boxes}{product.order_unit}")
    if rest:
        parts.append(f"{rest}{product.base_unit}")
    return " ".join(parts) or f"0{product.base_unit}"
