"""权限依赖单元测试；补货建议接口采用登录认证和数据范围隔离，不设角色限制。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.deps import allowed_store_ids, ensure_store_access, require_roles, user_store_id
from app.models import Region, Role, Store, User


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def permission_data(db):
    region1 = Region(code="R01", name="大区1")
    region2 = Region(code="R02", name="大区2")
    db.add_all([region1, region2])
    db.flush()

    store_a = Store(code="S001", name="门店A", region_id=region1.id)
    store_b = Store(code="S002", name="门店B", region_id=region1.id)
    store_c = Store(code="S003", name="门店C", region_id=region2.id)
    db.add_all([store_a, store_b, store_c])
    db.flush()

    users = {
        "admin": User(username="admin", password_hash="test", full_name="管理员", role=Role.ADMIN, is_active=True),
        "planner": User(username="planner", password_hash="test", full_name="计划员", role=Role.HQ_PLANNER, is_active=True),
        "region_manager": User(username="region_manager", password_hash="test", full_name="大区经理", role=Role.REGION_MANAGER, region_id=region1.id, is_active=True),
        "store_manager": User(username="store_manager", password_hash="test", full_name="门店店长", role=Role.STORE_MANAGER, store_id=store_a.id, region_id=region1.id, is_active=True),
        "store_clerk": User(username="store_clerk", password_hash="test", full_name="门店员工", role=Role.STORE_CLERK, store_id=store_a.id, region_id=region1.id, is_active=True),
        "warehouse": User(username="warehouse", password_hash="test", full_name="仓库人员", role=Role.WAREHOUSE, is_active=True),
    }
    db.add_all(users.values())
    db.commit()
    return {"region1": region1, "region2": region2, "store_a": store_a, "store_b": store_b, "store_c": store_c, **users}


def test_store_clerk_cannot_use_store_manager_role_returns_403(permission_data):
    check = require_roles(Role.STORE_MANAGER)
    with pytest.raises(HTTPException) as exc:
        check(user=permission_data["store_clerk"])
    assert exc.value.status_code == 403


def test_warehouse_cannot_use_hq_planner_role_returns_403(permission_data):
    check = require_roles(Role.HQ_PLANNER)
    with pytest.raises(HTTPException) as exc:
        check(user=permission_data["warehouse"])
    assert exc.value.status_code == 403


def test_require_roles_returns_user_when_role_is_allowed(permission_data):
    check = require_roles(Role.ADMIN, Role.HQ_PLANNER)
    assert check(user=permission_data["admin"]) is permission_data["admin"]


def test_store_manager_allowed_store_ids_contains_only_own_store(db, permission_data):
    assert allowed_store_ids(db=db, user=permission_data["store_manager"]) == [permission_data["store_a"].id]


def test_region_manager_allowed_store_ids_contains_only_own_region(db, permission_data):
    store_ids = allowed_store_ids(db=db, user=permission_data["region_manager"])
    assert set(store_ids) == {permission_data["store_a"].id, permission_data["store_b"].id}
    assert permission_data["store_c"].id not in store_ids


def test_warehouse_allowed_store_ids_is_unrestricted(db, permission_data):
    assert allowed_store_ids(db=db, user=permission_data["warehouse"]) is None


def test_store_manager_cannot_access_another_store_returns_403(db, permission_data):
    with pytest.raises(HTTPException) as exc:
        ensure_store_access(store_id=permission_data["store_b"].id, user=permission_data["store_manager"], db=db)
    assert exc.value.status_code == 403


def test_store_manager_can_access_own_store(db, permission_data):
    ensure_store_access(store_id=permission_data["store_a"].id, user=permission_data["store_manager"], db=db)


def test_region_manager_cannot_access_another_region_store_returns_403(db, permission_data):
    with pytest.raises(HTTPException) as exc:
        ensure_store_access(store_id=permission_data["store_c"].id, user=permission_data["region_manager"], db=db)
    assert exc.value.status_code == 403


def test_user_store_id_requires_store_binding_returns_400(permission_data):
    with pytest.raises(HTTPException) as exc:
        user_store_id(user=permission_data["warehouse"])
    assert exc.value.status_code == 400
