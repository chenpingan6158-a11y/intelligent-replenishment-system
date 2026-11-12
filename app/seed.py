"""演示数据生成器。

生成内容：
  * 2 个区域、6 家门店、6 类商品、48 个 SKU、12 道菜品（含配方）
  * 近 120 天的菜品销量与原料消耗（含星期周期、节假日尖峰、新品爬坡、随机噪声）
  * 初始库存与批次（部分临期、部分断货，用于触发预警）
  * 3 张不同状态的订货单，便于演示审批与收货

用法：python -m app.seed [--force]
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from .database import Base, SessionLocal, engine, init_db
from .models import (
    Alert,
    ApprovalRecord,
    Category,
    ConsumptionDaily,
    OperationLog,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Recipe,
    RecipeItem,
    Region,
    ReplenishmentPolicy,
    Role,
    SalesDaily,
    Stock,
    StockBatch,
    StockMovement,
    Store,
    UnitConversion,
    User,
)
from .security import hash_password

RNG = random.Random(20261111)
DAYS = 120

REGIONS = [("R01", "华东大区"), ("R02", "华南大区")]

STORES = [
    ("S001", "上海南京东路店", 1, "上海市黄浦区南京东路 300 号"),
    ("S002", "上海徐家汇店", 1, "上海市徐汇区漕溪北路 88 号"),
    ("S003", "杭州西湖店", 1, "杭州市西湖区延安路 168 号"),
    ("S004", "广州天河城店", 2, "广州市天河区天河路 208 号"),
    ("S005", "深圳福田店", 2, "深圳市福田区福华三路 118 号"),
    ("S006", "深圳南山店", 2, "深圳市南山区科技园南路 9 号"),
]

CATEGORIES = ["肉类", "蔬菜", "粮油", "调味料", "蛋豆制品", "酒水饮料"]

# (名称, 分类, 最小单位, 订货单位, 每订货单位含最小单位数, 保质期天, 每订货单位单价(元), 存储)
PRODUCTS = [
    ("五花肉", "肉类", "g", "箱", 10000, 5, 380.00, "冷藏"),
    ("牛腩", "肉类", "g", "箱", 10000, 5, 460.00, "冷藏"),
    ("鸡腿肉", "肉类", "g", "箱", 10000, 4, 260.00, "冷冻"),
    ("排骨", "肉类", "g", "箱", 8000, 5, 420.00, "冷藏"),
    ("鱼片", "肉类", "g", "箱", 5000, 3, 320.00, "冷冻"),
    ("培根", "肉类", "g", "箱", 4000, 15, 240.00, "冷藏"),
    ("土豆", "蔬菜", "g", "箱", 15000, 14, 90.00, "常温"),
    ("白菜", "蔬菜", "g", "箱", 10000, 7, 60.00, "冷藏"),
    ("青椒", "蔬菜", "g", "箱", 8000, 7, 110.00, "冷藏"),
    ("洋葱", "蔬菜", "g", "箱", 12000, 14, 80.00, "常温"),
    ("番茄", "蔬菜", "g", "箱", 10000, 6, 100.00, "冷藏"),
    ("生姜", "蔬菜", "g", "箱", 5000, 20, 70.00, "常温"),
    ("大蒜", "蔬菜", "g", "箱", 5000, 25, 85.00, "常温"),
    ("香菜", "蔬菜", "g", "箱", 3000, 4, 60.00, "冷藏"),
    ("生菜", "蔬菜", "g", "箱", 5000, 4, 75.00, "冷藏"),
    ("香菇", "蔬菜", "g", "箱", 4000, 6, 120.00, "冷藏"),
    ("大米", "粮油", "g", "袋", 25000, 180, 130.00, "常温"),
    ("面粉", "粮油", "g", "袋", 25000, 120, 95.00, "常温"),
    ("食用油", "粮油", "ml", "桶", 10000, 240, 110.00, "常温"),
    ("糯米", "粮油", "g", "袋", 10000, 180, 70.00, "常温"),
    ("生抽", "调味料", "ml", "箱", 12000, 365, 150.00, "常温"),
    ("老抽", "调味料", "ml", "箱", 12000, 365, 160.00, "常温"),
    ("蚝油", "调味料", "ml", "箱", 6000, 365, 130.00, "常温"),
    ("料酒", "调味料", "ml", "箱", 12000, 365, 120.00, "常温"),
    ("香醋", "调味料", "ml", "箱", 12000, 365, 110.00, "常温"),
    ("白糖", "调味料", "g", "袋", 10000, 365, 80.00, "常温"),
    ("食盐", "调味料", "g", "袋", 10000, 730, 40.00, "常温"),
    ("淀粉", "调味料", "g", "袋", 5000, 365, 55.00, "常温"),
    ("干辣椒", "调味料", "g", "袋", 2000, 365, 90.00, "常温"),
    ("花椒", "调味料", "g", "袋", 2000, 365, 100.00, "常温"),
    ("豆瓣酱", "调味料", "g", "箱", 8000, 365, 180.00, "常温"),
    ("鸡蛋", "蛋豆制品", "个", "箱", 360, 20, 240.00, "冷藏"),
    ("豆腐", "蛋豆制品", "g", "箱", 8000, 3, 60.00, "冷藏"),
    ("豆芽", "蛋豆制品", "g", "箱", 6000, 3, 45.00, "冷藏"),
    ("腐竹", "蛋豆制品", "g", "箱", 5000, 180, 130.00, "常温"),
    ("可口可乐", "酒水饮料", "ml", "箱", 14400, 270, 96.00, "常温"),
    ("雪碧", "酒水饮料", "ml", "箱", 14400, 270, 96.00, "常温"),
    ("矿泉水", "酒水饮料", "ml", "箱", 24000, 365, 48.00, "常温"),
    ("啤酒", "酒水饮料", "ml", "箱", 12000, 180, 120.00, "常温"),
    ("橙汁", "酒水饮料", "ml", "箱", 12000, 90, 108.00, "冷藏"),
    ("酸梅汤", "酒水饮料", "ml", "箱", 12000, 120, 96.00, "常温"),
    ("牛肉丸", "肉类", "g", "箱", 5000, 90, 220.00, "冷冻"),
    ("年糕", "粮油", "g", "箱", 8000, 30, 88.00, "常温"),
    ("米粉", "粮油", "g", "箱", 10000, 180, 76.00, "常温"),
    ("花生米", "粮油", "g", "箱", 5000, 180, 92.00, "常温"),
    ("辣椒油", "调味料", "ml", "箱", 6000, 365, 140.00, "常温"),
    ("柠檬", "蔬菜", "个", "箱", 200, 14, 110.00, "冷藏"),
]

# (菜品名, 单价元, [(商品名, 每份用量(最小单位))])
RECIPES = [
    ("红烧肉饭", 32.0, [("五花肉", 180), ("大米", 150), ("生抽", 15), ("白糖", 8), ("生姜", 5)]),
    ("土豆牛腩饭", 36.0, [("牛腩", 160), ("土豆", 200), ("大米", 150), ("老抽", 12), ("洋葱", 30)]),
    ("秘制鸡腿饭", 28.0, [("鸡腿肉", 180), ("大米", 150), ("生抽", 12), ("大蒜", 4), ("食用油", 15)]),
    ("排骨年糕", 34.0, [("排骨", 170), ("年糕", 180), ("生抽", 15), ("白糖", 6), ("食用油", 12)]),
    ("酸菜鱼饭", 38.0, [("鱼片", 160), ("大米", 150), ("干辣椒", 5), ("花椒", 3), ("食用油", 18)]),
    ("香菇滑鸡饭", 30.0, [("鸡腿肉", 150), ("香菇", 60), ("大米", 150), ("蚝油", 10), ("淀粉", 6)]),
    ("麻婆豆腐饭", 24.0, [("豆腐", 250), ("大米", 150), ("豆瓣酱", 25), ("花椒", 2), ("食用油", 15)]),
    ("青椒肉丝饭", 26.0, [("五花肉", 120), ("青椒", 120), ("大米", 150), ("生抽", 10), ("淀粉", 5)]),
    ("番茄鸡蛋面", 22.0, [("番茄", 150), ("鸡蛋", 2), ("面粉", 200), ("食用油", 12), ("食盐", 3)]),
    ("培根意面", 33.0, [("培根", 60), ("面粉", 180), ("洋葱", 40), ("食用油", 15), ("食盐", 3)]),
    ("腐竹炒肉饭", 27.0, [("腐竹", 70), ("五花肉", 100), ("大米", 150), ("青椒", 60), ("生抽", 10)]),
    ("花生米拌面", 21.0, [("花生米", 50), ("面粉", 200), ("香醋", 12), ("辣椒油", 8), ("香菜", 8)]),
]

DRINK_RECIPES = [
    ("可口可乐(杯)", 6.0, [("可口可乐", 330)]),
    ("雪碧(杯)", 6.0, [("雪碧", 330)]),
    ("矿泉水(瓶)", 3.0, [("矿泉水", 550)]),
    ("鲜榨橙汁", 12.0, [("橙汁", 300), ("柠檬", 0.2)]),
]

USERS = [
    ("admin", "admin123", "系统管理员", Role.ADMIN, None, None),
    ("hq", "hq123", "总部计划员-林可", Role.HQ_PLANNER, None, None),
    ("region_east", "region123", "华东区域经理-周敏", Role.REGION_MANAGER, None, 1),
    ("region_south", "region123", "华南区域经理-陈磊", Role.REGION_MANAGER, None, 2),
    ("sm001", "sm123", "南京东路店长-王强", Role.STORE_MANAGER, 1, None),
    ("sm002", "sm123", "徐家汇店长-李娜", Role.STORE_MANAGER, 2, None),
    ("clerk001", "clerk123", "南京东路店员-赵鹏", Role.STORE_CLERK, 1, None),
    ("wh", "wh123", "中央厨房-吴师傅", Role.WAREHOUSE, None, None),
]


def _daily_demand(base: float, day: date, trend: float) -> int:
    """星期因子 + 趋势 + 促销尖峰 + 噪声。"""
    weekday_factor = {0: 0.85, 1: 0.9, 2: 0.95, 3: 1.0, 4: 1.25, 5: 1.4, 6: 1.2}[day.weekday()]
    value = base * weekday_factor * (1 + trend * ((day - date.today()).days / 30))
    # 每月 1 日和 15 日做会员日活动
    if day.day in (1, 15):
        value *= 1.35
    # 节假日尖峰（简化为若干固定日期）
    if (day.month, day.day) in {(1, 1), (5, 1), (10, 1), (10, 2), (10, 3)}:
        value *= 1.6
    return max(0, int(value * RNG.uniform(0.85, 1.15)))


def seed(force: bool = False) -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.execute(select(func.count(Product.id))).scalar() or 0
        if existing and not force:
            print(f"[seed] 已存在 {existing} 个商品，跳过。使用 --force 重建（会清空数据）。")
            return
        if force:
            print("[seed] 清空现有数据…")
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)

        # ---------------- 组织与账号 ----------------
        regions = [Region(code=c, name=n) for c, n in REGIONS]
        db.add_all(regions)
        db.flush()

        stores = [Store(code=c, name=n, region_id=rid, address=addr, is_active=True) for c, n, rid, addr in STORES]
        db.add_all(stores)
        db.flush()

        for username, pwd, full_name, role, store_id, region_id in USERS:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(pwd),
                    full_name=full_name,
                    role=role,
                    store_id=store_id,
                    region_id=region_id,
                    is_active=True,
                )
            )
        db.flush()

        # ---------------- 主数据 ----------------
        categories = {name: Category(name=name) for name in CATEGORIES}
        db.add_all(categories.values())
        db.flush()

        products: dict[str, Product] = {}
        for idx, (name, cat, base_unit, order_unit, per_unit, shelf, price, storage) in enumerate(PRODUCTS, start=1):
            product = Product(
                sku=f"SKU{idx:04d}",
                name=name,
                category_id=categories[cat].id,
                base_unit=base_unit,
                order_unit=order_unit,
                base_per_order_unit=per_unit,
                shelf_life_days=shelf,
                storage_type=storage,
                unit_price_cents=int(price * 100),
                is_active=True,
            )
            db.add(product)
            products[name] = product
        db.flush()

        for product in products.values():
            db.add(
                UnitConversion(
                    product_id=product.id,
                    from_unit=product.order_unit,
                    to_unit=product.base_unit,
                    factor=product.base_per_order_unit,
                )
            )

        recipes: list[tuple[Recipe, float]] = []
        for idx, (name, price, items) in enumerate(RECIPES + DRINK_RECIPES, start=1):
            recipe = Recipe(code=f"D{idx:03d}", name=name, price_cents=int(price * 100))
            db.add(recipe)
            db.flush()
            for product_name, qty in items:
                db.add(
                    RecipeItem(
                        recipe_id=recipe.id,
                        product_id=products[product_name].id,
                        qty_base=max(1, int(qty)),
                    )
                )
            # 基准日均销量：菜品 60-140 份，饮料 90-200 份
            base = RNG.uniform(60, 140) if idx <= len(RECIPES) else RNG.uniform(90, 200)
            recipes.append((recipe, base))
        db.flush()

        # ---------------- 补货策略 ----------------
        for store in stores:
            for product in products.values():
                db.add(
                    ReplenishmentPolicy(
                        store_id=store.id,
                        product_id=product.id,
                        lead_time_days=2 if product.storage_type != "冷冻" else 3,
                        order_cycle_days=3,
                        moq_base=product.base_per_order_unit,
                        pack_multiple_base=product.base_per_order_unit,
                        max_stock_base=product.base_per_order_unit * 12,
                        service_level_z=165,
                        is_enabled=True,
                    )
                )
        db.flush()

        # ---------------- 历史销量与消耗 ----------------
        today = date.today()
        start = today - timedelta(days=DAYS - 1)
        sales_rows: list[SalesDaily] = []
        consumption: dict[tuple[int, date, int], int] = {}

        for store_index, store in enumerate(stores):
            store_factor = RNG.uniform(0.8, 1.2)
            for recipe, base in recipes:
                trend = RNG.uniform(-0.05, 0.12)
                # 每家店有少量菜品表现差异
                dish_factor = store_factor * RNG.uniform(0.7, 1.25)
                for offset in range(DAYS):
                    day = start + timedelta(days=offset)
                    qty = _daily_demand(base * dish_factor, day, trend)
                    if qty <= 0:
                        continue
                    sales_rows.append(
                        SalesDaily(store_id=store.id, biz_date=day, recipe_id=recipe.id, qty=qty)
                    )
                    items = db.execute(select(RecipeItem).where(RecipeItem.recipe_id == recipe.id)).scalars().all()
                    for item in items:
                        key = (store.id, day, item.product_id)
                        consumption[key] = consumption.get(key, 0) + qty * item.qty_base

        db.add_all(sales_rows)
        db.flush()

        consumption_rows = [
            ConsumptionDaily(store_id=sid, biz_date=day, product_id=pid, qty_base=qty)
            for (sid, day, pid), qty in consumption.items()
        ]
        db.add_all(consumption_rows)
        db.flush()

        # ---------------- 初始库存与批次 ----------------
        for store in stores:
            for product in products.values():
                # 3 天左右的用量作为期初库存
                recent = [
                    consumption.get((store.id, today - timedelta(days=i), product.id), 0) for i in range(1, 8)
                ]
                daily_avg = sum(recent) / max(1, len([x for x in recent if x > 0]) or 1)
                cover_days = 3 if product.category_id != categories["酒水饮料"].id else 6
                qty = int(daily_avg * cover_days)
                # 10% 的商品制造断货，用于触发预警
                if RNG.random() < 0.10:
                    qty = 0
                # 5% 的商品超量积压，用于触发滞销
                if RNG.random() < 0.05:
                    qty = int(daily_avg * 30)

                db.add(Stock(store_id=store.id, product_id=product.id, qty_base=qty, locked_base=0, version=0))
                if qty <= 0:
                    continue

                # 拆成两个批次：一个正常、一个临期
                part = int(qty * RNG.uniform(0.45, 0.7))
                for batch_qty, prod_offset, suffix in (
                    (part, RNG.randint(1, 3), "A"),
                    (qty - part, product.shelf_life_days - RNG.randint(0, 2), "B"),
                ):
                    if batch_qty <= 0:
                        continue
                    production = today - timedelta(days=max(0, prod_offset))
                    expiry = production + timedelta(days=max(1, product.shelf_life_days))
                    db.add(
                        StockBatch(
                            store_id=store.id,
                            product_id=product.id,
                            batch_no=f"{store.code}-{product.sku}-{suffix}",
                            production_date=production,
                            expiry_date=expiry,
                            qty_base=batch_qty,
                        )
                    )
                    db.add(
                        StockMovement(
                            store_id=store.id,
                            product_id=product.id,
                            movement_type="IN",
                            qty_base=batch_qty,
                            unit_cost_cents=product.unit_price_cents,
                            ref_type="INIT",
                            ref_no=f"期初-{store.code}",
                            operator_id=None,
                            note="期初库存导入",
                            created_at=datetime.combine(production, datetime.min.time()),
                        )
                    )
        db.flush()

        # ---------------- 订货单样例 ----------------
        store_ids = [s.id for s in stores]
        _seed_orders(db, store_ids, products, recipes)

        # ---------------- 预警 ----------------
        db.commit()

        # 扫描预警需要已提交数据，单独调用
        from .services import alerting

        alerting.scan_all(db)
        db.commit()

        counts = {
            "区域": db.execute(select(func.count(Region.id))).scalar(),
            "门店": db.execute(select(func.count(Store.id))).scalar(),
            "商品": db.execute(select(func.count(Product.id))).scalar(),
            "菜品": db.execute(select(func.count(Recipe.id))).scalar(),
            "销量记录": db.execute(select(func.count(SalesDaily.id))).scalar(),
            "消耗记录": db.execute(select(func.count(ConsumptionDaily.id))).scalar(),
            "库存批次": db.execute(select(func.count(StockBatch.id))).scalar(),
            "订货单": db.execute(select(func.count(PurchaseOrder.id))).scalar(),
            "预警": db.execute(select(func.count(Alert.id))).scalar(),
        }
        print("[seed] 完成：")
        for key, value in counts.items():
            print(f"    {key}: {value}")
    finally:
        db.close()


def _seed_orders(db, store_ids, products, recipes) -> None:
    """造 3 张不同状态的订单，供审批 / 收货演示。"""
    samples = [
        (store_ids[0], OrderStatus.SUBMITTED, [("五花肉", 2), ("大米", 3), ("鸡蛋", 2)]),
        (store_ids[1], OrderStatus.CONFIRMED, [("牛腩", 2), ("土豆", 3), ("食用油", 1)]),
        (store_ids[3], OrderStatus.APPROVED, [("鱼片", 2), ("豆腐", 4), ("可口可乐", 2)]),
    ]
    for idx, (store_id, status, lines) in enumerate(samples, start=1):
        order = PurchaseOrder(
            order_no=f"PO{date.today():%Y%m%d}{1000 + idx}",
            store_id=store_id,
            status=status,
            total_cents=0,
            created_by=5,
            submitted_at=datetime.now().replace(microsecond=0),
            expected_delivery_date=date.today() + timedelta(days=2),
            remark="演示数据",
        )
        db.add(order)
        db.flush()
        total = 0
        for name, qty in lines:
            product = products[name]
            amount = qty * product.unit_price_cents
            total += amount
            db.add(
                PurchaseOrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    suggest_qty_base=qty * product.base_per_order_unit,
                    order_qty_base=qty * product.base_per_order_unit,
                    unit_price_cents=product.unit_price_cents,
                    amount_cents=amount,
                )
            )
        order.total_cents = total
        db.add(ApprovalRecord(order_id=order.id, action="SUBMIT", operator_id=5, opinion="提交订货单"))
        if status in (OrderStatus.APPROVED, OrderStatus.CONFIRMED):
            db.add(ApprovalRecord(order_id=order.id, action="APPROVE", operator_id=3, opinion="审批通过"))
        if status == OrderStatus.CONFIRMED:
            db.add(ApprovalRecord(order_id=order.id, action="CONFIRM", operator_id=8, opinion="已发货"))
        db.flush()


if __name__ == "__main__":
    seed(force="--force" in sys.argv)
