# Copilot 上下文包：为 RBAC 权限层补充越权测试

> 用途：拖拽本文件到 VS Code Copilot Chat 输入框，再配上文末的 prompt。
> 本文件是给 AI 的上下文，不是项目文档。

## 1. 项目概况

- 后端：FastAPI + SQLAlchemy 2.x + SQLite，Python 3.13
- 权限模型：**6 角色 RBAC + 数据范围隔离** 双层校验
- 目录：

```
app/
├── deps.py          # 权限层：get_current_user / require_roles / allowed_store_ids
│                    #        ensure_store_access / user_store_id   ← 本次被测对象
├── models.py        # Role（字符串常量类）、User、Store、Region
├── security.py      # decode_access_token
├── database.py      # Base、get_db
└── routers/
    ├── auth.py        prefix=/api/auth
    ├── master.py      prefix=/api/master
    ├── inventory.py   prefix=/api/inventory
    ├── replenishment.py prefix=/api/replenishment
    ├── orders.py      prefix=/api/orders
    └── dashboard.py   prefix=/api
tests/
├── test_forecast.py  # 18 例
├── test_inventory.py # 14 例
└── test_orders.py    # 14 例
```

## 2. 测试约定（重要，务必遵守）

- **没有 `conftest.py`**，每个测试文件自己定义 `db` fixture
- 测试**不起 HTTP 服务、不用 TestClient**，全部直接调用 service / deps 函数
- `db` fixture 写法（照抄即可）：

```python
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
    # ... 构造 Region / Store / User / Product 等种子数据
    yield session
    session.close()
```

- 断言风格：`with pytest.raises(HTTPException) as exc: ...` 然后 `assert exc.value.status_code == 403`
- 现有测试全部是同步函数，不使用 async

## 3. 权限层实现（被测对象，节选关键部分）

```python
ALL_SCOPE_ROLES = {Role.ADMIN, Role.HQ_PLANNER, Role.WAREHOUSE}

def get_current_user(credentials=Depends(bearer_scheme), db=Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(401, "未登录或登录已过期")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "令牌无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "用户不存在或已停用")
    return user

def require_roles(*roles: str):
    """角色守卫。用法：Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))"""
    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "当前角色无权执行该操作")
        return user
    return _guard

def allowed_store_ids(db, user) -> list[int] | None:
    """返回可访问的门店 id 列表；None 表示不受限（总部/仓库/管理员）。"""
    if user.role in ALL_SCOPE_ROLES:
        return None
    if user.role == Role.REGION_MANAGER:
        rows = db.execute(select(Store.id).where(Store.region_id == user.region_id)).scalars().all()
        return list(rows)
    if user.store_id:
        return [user.store_id]
    return []

def ensure_store_access(db, user, store_id: int) -> None:
    scope = allowed_store_ids(db, user)
    if scope is not None and store_id not in scope:
        raise HTTPException(403, "无权访问该门店数据")

def user_store_id(user: User) -> int:
    if not user.store_id:
        raise HTTPException(400, "当前账号未绑定门店")
    return user.store_id
```

## 4. Role 定义（是字符串常量类，不是 Enum）

```python
class Role:
    ADMIN = "ADMIN"                      # 系统管理员
    HQ_PLANNER = "HQ_PLANNER"            # 总部供应链计划员
    REGION_MANAGER = "REGION_MANAGER"    # 区域经理
    STORE_MANAGER = "STORE_MANAGER"      # 门店店长
    STORE_CLERK = "STORE_CLERK"          # 门店员工
    WAREHOUSE = "WAREHOUSE"              # 中央厨房 / 中心仓
```

## 5. User 表字段

`id, username, password_hash, full_name, role, store_id(可空), region_id(可空), is_active, created_at`

## 6. 各端点的角色要求（用于设计越权场景）

| 端点 | 允许角色 |
|---|---|
| POST /api/inventory/receive 收货入库 | STORE_MANAGER, STORE_CLERK, WAREHOUSE, ADMIN |
| POST /api/inventory/outbound 领用出库 | STORE_MANAGER, STORE_CLERK, ADMIN |
| POST /api/inventory/loss 报损 | STORE_MANAGER, STORE_CLERK, ADMIN |
| POST /api/inventory/stocktake 建盘点单 | STORE_MANAGER, ADMIN |
| POST /api/inventory/transfer 跨店调拨 | REGION_MANAGER, HQ_PLANNER, ADMIN |
| GET /api/inventory/stores-overview | 任意登录用户（数据范围受限） |
| POST /api/orders 创建订货单 | STORE_MANAGER, STORE_CLERK, ADMIN |
| POST /api/orders/{id}/approve 审批通过 | APPROVER_ROLES |
| POST /api/orders/{id}/reject 审批驳回 | APPROVER_ROLES |
| POST /api/orders/{id}/confirm 中央厨房发货 | WAREHOUSE, ADMIN |
| POST /api/orders/{id}/receive 门店收货 | STORE_MANAGER, STORE_CLERK, ADMIN |
| POST /api/orders/{id}/close 归档 | ADMIN, HQ_PLANNER |
| POST /api/alerts/scan 触发预警扫描 | STORE_MANAGER, HQ_PLANNER, ADMIN, REGION_MANAGER |
| GET /api/master/users 人员列表 | ADMIN, HQ_PLANNER |
| PUT /api/master/users/{id}/status 上岗/离职 | ADMIN |
| POST /api/master/stores 新建门店 | ADMIN, HQ_PLANNER |
| POST /api/master/products 新建商品 | ADMIN, HQ_PLANNER |

## 7. 数据范围规则（越权测试的核心）

| 角色 | 可见门店范围 |
|---|---|
| ADMIN / HQ_PLANNER / WAREHOUSE | 全部（`allowed_store_ids` 返回 None） |
| REGION_MANAGER | 仅本 `region_id` 下所有门店 |
| STORE_MANAGER / STORE_CLERK | 仅本 `store_id` 对应门店 |
