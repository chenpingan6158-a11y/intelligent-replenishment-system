"""FastAPI 依赖：当前用户、角色守卫、数据权限范围。"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Role, Store, User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

ALL_SCOPE_ROLES = {Role.ADMIN, Role.HQ_PLANNER, Role.WAREHOUSE}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    """角色守卫。用法：Depends(require_roles(Role.ADMIN, Role.HQ_PLANNER))"""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行该操作")
        return user

    return _guard


def allowed_store_ids(db: Session, user: User) -> list[int] | None:
    """返回可访问的门店 id 列表；None 表示不受限（总部 / 仓库 / 管理员）。"""
    if user.role in ALL_SCOPE_ROLES:
        return None
    if user.role == Role.REGION_MANAGER:
        rows = db.execute(select(Store.id).where(Store.region_id == user.region_id)).scalars().all()
        return list(rows)
    if user.store_id:
        return [user.store_id]
    return []


def ensure_store_access(db: Session, user: User, store_id: int) -> None:
    scope = allowed_store_ids(db, user)
    if scope is not None and store_id not in scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该门店数据")


def user_store_id(user: User) -> int:
    if not user.store_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号未绑定门店")
    return user.store_id
