"""认证相关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..config import REGISTER_QUOTAS
from ..database import get_db
from ..deps import get_current_user
from ..models import Region, Role, Store, User
from ..schemas import LoginIn, RegisterIn
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["认证"])

ROLE_LABELS = {
    Role.ADMIN: "系统管理员",
    Role.HQ_PLANNER: "总部计划员",
    Role.REGION_MANAGER: "区域经理",
    Role.STORE_MANAGER: "门店店长",
    Role.STORE_CLERK: "门店员工",
    Role.WAREHOUSE: "中央厨房",
}


def serialize_user(db: Session, user: User) -> dict:
    store = db.get(Store, user.store_id) if user.store_id else None
    return {
        "id": user.id,
        "username": user.username,
        "fullName": user.full_name,
        "role": user.role,
        "roleLabel": ROLE_LABELS.get(user.role, user.role),
        "storeId": user.store_id,
        "storeName": store.name if store else None,
        "regionId": user.region_id,
    }


@router.post("/login", summary="登录获取令牌")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    token = create_access_token(str(user.id), {"role": user.role, "name": user.full_name})
    return ok({"token": token, "user": serialize_user(db, user)})


@router.get("/me", summary="当前登录用户")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(serialize_user(db, user))


# 允许自助注册的角色：不含 ADMIN（管理员账号由种子数据/运维掌握，防止越权自助创建）
REGISTER_ROLES = {
    Role.HQ_PLANNER,
    Role.REGION_MANAGER,
    Role.STORE_MANAGER,
    Role.STORE_CLERK,
    Role.WAREHOUSE,
}
# 各角色必填的归属字段：门店类角色必须挂到具体门店，区域经理必须挂到具体区域
ROLE_NEEDS_STORE = {Role.STORE_MANAGER, Role.STORE_CLERK}
ROLE_NEEDS_REGION = {Role.REGION_MANAGER}


@router.get("/options", summary="注册表单选项：角色/区域/门店（免登录）")
def register_options(db: Session = Depends(get_db)):
    regions = db.execute(select(Region).order_by(Region.id)).scalars().all()
    stores = db.execute(select(Store).order_by(Store.id)).scalars().all()
    return ok(
        {
            "roles": [
                {"value": r, "label": ROLE_LABELS[r]}
                for r in (
                    Role.STORE_MANAGER,
                    Role.STORE_CLERK,
                    Role.REGION_MANAGER,
                    Role.HQ_PLANNER,
                    Role.WAREHOUSE,
                )
            ],
            "regions": [{"id": g.id, "name": g.name} for g in regions],
            "stores": [{"id": s.id, "name": s.name} for s in stores],
            "quotas": {
                r: {"scope": sc, "limit": lim, "scopeLabel": {"store": "每门店", "region": "每大区", "global": "全系统"}[sc]}
                for r, (sc, lim) in REGISTER_QUOTAS.items()
            },
        }
    )


@router.post("/register", summary="自助注册新账号")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if body.role not in REGISTER_ROLES:
        raise HTTPException(status_code=400, detail="不支持注册该角色")
    if body.role in ROLE_NEEDS_STORE and not body.store_id:
        raise HTTPException(status_code=400, detail="该角色必须选择所属门店")
    if body.role in ROLE_NEEDS_REGION and not body.region_id:
        raise HTTPException(status_code=400, detail="该角色必须选择所属区域")
    if body.role in ROLE_NEEDS_STORE:
        store = db.get(Store, body.store_id)
        if store is None:
            raise HTTPException(status_code=400, detail="所选门店不存在")
        region_id = store.region_id  # 门店角色自动归入门店所在区域，便于区域经理按区域管控
    else:
        region_id = body.region_id
        if region_id is not None and db.get(Region, region_id) is None:
            raise HTTPException(status_code=400, detail="所选区域不存在")

    # 人数上限校验：在职（is_active）用户才占用名额，离职后名额自动释放
    scope, limit = REGISTER_QUOTAS.get(body.role, (None, None))
    if limit is not None:
        cond = [User.role == body.role, User.is_active.is_(True)]
        if scope == "store":
            cond.append(User.store_id == body.store_id)
        elif scope == "region":
            cond.append(User.region_id == region_id)
        current = db.execute(select(func.count(User.id)).where(*cond)).scalar() or 0
        if current >= limit:
            where = {"store": "该门店", "region": "该大区", "global": "全系统"}[scope]
            role_label = ROLE_LABELS[body.role]
            raise HTTPException(
                status_code=400,
                detail=f"人数到达上限：{where}{role_label}编制 {limit} 名，当前已有 {current} 名在职，无法注册",
            )

    exists = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=400, detail="用户名已存在，请换一个")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        store_id=body.store_id if body.role in ROLE_NEEDS_STORE else None,
        region_id=region_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id), {"role": user.role, "name": user.full_name})
    return ok({"token": token, "user": serialize_user(db, user)}, "注册成功并已登录")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(serialize_user(db, user))


@router.get("/accounts", summary="演示账号列表（免登录查看，便于评审者体验）")
def accounts(db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return ok(
        [
            {
                "username": u.username,
                "fullName": u.full_name,
                "role": u.role,
                "roleLabel": ROLE_LABELS.get(u.role, u.role),
                "storeName": (db.get(Store, u.store_id).name if u.store_id else None),
            }
            for u in rows
        ]
    )


@router.post("/reset-password", summary="重置口令（管理员/演示用）")
def reset_password(username: str, new_password: str, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(new_password)
    db.commit()
    return ok(True, "口令已重置")
