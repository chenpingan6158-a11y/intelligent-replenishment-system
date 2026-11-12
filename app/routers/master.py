"""主数据接口：区域、门店、分类、商品、补货策略、配方、账号。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..database import get_db
from ..deps import allowed_store_ids, get_current_user, require_roles
from ..models import (
    Category,
    Product,
    Recipe,
    RecipeItem,
    Region,
    ReplenishmentPolicy,
    Role,
    Store,
    UnitConversion,
    User,
)
from ..schemas import CategoryIn, PolicyIn, ProductIn, RecipeIn, RegionIn, StoreIn, UserStatusIn

router = APIRouter(prefix="/api/master", tags=["主数据"])


# ------------------------------------------------------------------ 区域 / 门店
@router.get("/regions")
def list_regions(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(select(Region).order_by(Region.id)).scalars().all()
    return ok([{"id": r.id, "code": r.code, "name": r.name} for r in rows])


@router.post("/regions")
def create_region(body: RegionIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    if db.execute(select(Region).where(Region.code == body.code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="区域编码已存在")
    region = Region(code=body.code, name=body.name)
    db.add(region)
    db.commit()
    return ok({"id": region.id}, "区域已创建")


@router.get("/stores")
def list_stores(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scope = allowed_store_ids(db, user)
    stmt = select(Store).order_by(Store.id)
    if scope is not None:
        stmt = stmt.where(Store.id.in_(scope or [-1]))
    rows = db.execute(stmt).scalars().all()
    return ok(
        [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "regionId": s.region_id,
                "regionName": (db.get(Region, s.region_id).name if s.region_id else ""),
                "address": s.address,
                "isActive": s.is_active,
            }
            for s in rows
        ]
    )


@router.post("/stores")
def create_store(body: StoreIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    if db.execute(select(Store).where(Store.code == body.code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="门店编码已存在")
    store = Store(**body.model_dump())
    db.add(store)
    db.commit()
    return ok({"id": store.id}, "门店已创建")


# ------------------------------------------------------------------ 分类 / 商品
@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(select(Category).order_by(Category.id)).scalars().all()
    return ok([{"id": c.id, "name": c.name} for c in rows])


@router.post("/categories")
def create_category(body: CategoryIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    if db.execute(select(Category).where(Category.name == body.name)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="分类已存在")
    category = Category(name=body.name)
    db.add(category)
    db.commit()
    return ok({"id": category.id}, "分类已创建")


def _serialize_product(db: Session, p: Product) -> dict:
    category = db.get(Category, p.category_id)
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "categoryId": p.category_id,
        "categoryName": category.name if category else "",
        "baseUnit": p.base_unit,
        "orderUnit": p.order_unit,
        "basePerOrderUnit": p.base_per_order_unit,
        "shelfLifeDays": p.shelf_life_days,
        "storageType": p.storage_type,
        "unitPriceCents": p.unit_price_cents,
        "isActive": p.is_active,
    }


@router.get("/products")
def list_products(
    keyword: str = "",
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Product).order_by(Product.id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((Product.name.like(like)) | (Product.sku.like(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    rows = db.execute(stmt).scalars().all()
    return ok([_serialize_product(db, p) for p in rows])


@router.post("/products")
def create_product(body: ProductIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    if db.execute(select(Product).where(Product.sku == body.sku)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="SKU 已存在")
    product = Product(**body.model_dump())
    db.add(product)
    db.flush()
    # BR-01：登记订货单位 → 最小单位的换算
    db.add(
        UnitConversion(
            product_id=product.id,
            from_unit=product.order_unit,
            to_unit=product.base_unit,
            factor=product.base_per_order_unit,
        )
    )
    db.commit()
    return ok({"id": product.id}, "商品已创建")


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    body: ProductIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER)),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    for key, value in body.model_dump().items():
        setattr(product, key, value)
    conv = db.execute(
        select(UnitConversion).where(
            UnitConversion.product_id == product_id,
            UnitConversion.from_unit == product.order_unit,
            UnitConversion.to_unit == product.base_unit,
        )
    ).scalar_one_or_none()
    if conv:
        conv.factor = product.base_per_order_unit
    else:
        db.add(
            UnitConversion(
                product_id=product_id,
                from_unit=product.order_unit,
                to_unit=product.base_unit,
                factor=product.base_per_order_unit,
            )
        )
    db.commit()
    return ok(True, "商品已更新")


# ------------------------------------------------------------------ 补货策略
@router.get("/policies")
def list_policies(store_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scope = allowed_store_ids(db, user)
    stmt = select(ReplenishmentPolicy).order_by(ReplenishmentPolicy.product_id)
    target_store = store_id or user.store_id
    if target_store:
        stmt = stmt.where(ReplenishmentPolicy.store_id == target_store)
    elif scope is not None:
        stmt = stmt.where(ReplenishmentPolicy.store_id.in_(scope or [-1]))
    rows = db.execute(stmt).scalars().all()
    return ok(
        [
            {
                "id": r.id,
                "storeId": r.store_id,
                "productId": r.product_id,
                "productName": (db.get(Product, r.product_id).name if db.get(Product, r.product_id) else ""),
                "leadTimeDays": r.lead_time_days,
                "orderCycleDays": r.order_cycle_days,
                "moqBase": r.moq_base,
                "packMultipleBase": r.pack_multiple_base,
                "maxStockBase": r.max_stock_base,
                "serviceLevelZ": r.service_level_z,
                "isEnabled": r.is_enabled,
            }
            for r in rows
        ]
    )


@router.post("/policies")
def upsert_policy(body: PolicyIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER, Role.STORE_MANAGER))):
    policy = db.execute(
        select(ReplenishmentPolicy).where(
            ReplenishmentPolicy.store_id == body.store_id,
            ReplenishmentPolicy.product_id == body.product_id,
        )
    ).scalar_one_or_none()
    if policy is None:
        policy = ReplenishmentPolicy(**body.model_dump())
        db.add(policy)
    else:
        for key, value in body.model_dump().items():
            setattr(policy, key, value)
    db.commit()
    return ok({"id": policy.id}, "补货策略已保存")


# ------------------------------------------------------------------ 配方
@router.get("/recipes")
def list_recipes(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(select(Recipe).order_by(Recipe.id)).scalars().all()
    result = []
    for r in rows:
        items = db.execute(select(RecipeItem).where(RecipeItem.recipe_id == r.id)).scalars().all()
        result.append(
            {
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "priceCents": r.price_cents,
                "items": [
                    {
                        "productId": i.product_id,
                        "productName": (db.get(Product, i.product_id).name if db.get(Product, i.product_id) else ""),
                        "qtyBase": i.qty_base,
                        "unit": (db.get(Product, i.product_id).base_unit if db.get(Product, i.product_id) else ""),
                    }
                    for i in items
                ],
            }
        )
    return ok(result)


@router.post("/recipes")
def create_recipe(body: RecipeIn, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    if db.execute(select(Recipe).where(Recipe.code == body.code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="菜品编码已存在")
    recipe = Recipe(code=body.code, name=body.name, price_cents=body.price_cents)
    db.add(recipe)
    db.flush()
    for item in body.items:
        db.add(RecipeItem(recipe_id=recipe.id, product_id=item.product_id, qty_base=item.qty_base))
    db.commit()
    return ok({"id": recipe.id}, "菜品已创建")


# ------------------------------------------------------------------ 账号（人员管理）
@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return ok(
        [
            {
                "id": u.id,
                "username": u.username,
                "fullName": u.full_name,
                "role": u.role,
                "storeId": u.store_id,
                "storeName": (db.get(Store, u.store_id).name if u.store_id else None),
                "regionId": u.region_id,
                "regionName": (db.get(Region, u.region_id).name if u.region_id else None),
                "isActive": u.is_active,
            }
            for u in rows
        ]
    )


@router.put("/users/{user_id}/status", summary="人员上岗 / 离职（仅管理员）")
def set_user_status(
    user_id: int,
    body: UserStatusIn,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(Role.ADMIN)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == operator.id:
        raise HTTPException(status_code=400, detail="不能对自己执行离职操作")
    if user.role == Role.ADMIN and not body.is_active:
        raise HTTPException(status_code=400, detail="系统管理员账号不允许离职停用")
    user.is_active = body.is_active
    db.commit()
    return ok(
        {"id": user.id, "username": user.username, "isActive": user.is_active},
        "已办理离职，账号停用（不占注册名额）" if not body.is_active else "已办理上岗，账号恢复",
    )
