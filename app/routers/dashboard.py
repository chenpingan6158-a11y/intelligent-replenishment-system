"""预警与看板接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..api_utils import ok
from ..database import get_db
from ..deps import allowed_store_ids, ensure_store_access, get_current_user, require_roles, user_store_id
from ..models import Alert, Role, User
from ..schemas import AlertHandleIn
from ..services import alerting, metrics

router = APIRouter(prefix="/api", tags=["预警与看板"])


@router.get("/alerts", summary="预警列表")
def list_alerts(
    store_id: int | None = None,
    status: str = "OPEN",
    alert_type: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if store_id:
        ensure_store_access(db, user, store_id)
        scope = [store_id]
    else:
        scope = allowed_store_ids(db, user)
    return ok(alerting.list_alerts(db, scope, status=status, alert_type=alert_type))


@router.get("/alerts/summary", summary="预警统计")
def alert_summary(store_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scope = [store_id] if store_id else allowed_store_ids(db, user)
    if store_id:
        ensure_store_access(db, user, store_id)
    return ok(alerting.summary(db, scope))


@router.post("/alerts/scan", summary="触发预警扫描")
def scan(
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.STORE_MANAGER, Role.HQ_PLANNER, Role.ADMIN, Role.REGION_MANAGER)),
):
    if store_id:
        ensure_store_access(db, user, store_id)
        result = alerting.scan_store(db, store_id)
    else:
        sid = user.store_id
        result = alerting.scan_store(db, sid) if sid else alerting.scan_all(db)
    db.commit()
    return ok(result, "预警扫描完成")


@router.post("/alerts/{alert_id}/handle", summary="处理 / 忽略预警")
def handle(
    alert_id: int,
    body: AlertHandleIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="预警不存在")
    ensure_store_access(db, user, alert.store_id)
    alerting.handle_alert(db, alert, user.id, body.action, body.note)
    db.commit()
    return ok(True, "已处理")


@router.get("/dashboard/overview", summary="经营看板总览")
def overview(
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if store_id:
        ensure_store_access(db, user, store_id)
        scope = [store_id]
    else:
        scope = allowed_store_ids(db, user)
        if user.store_id:
            store_id = user.store_id
    data = metrics.overview(db, scope, store_id=store_id or user.store_id)
    data["alertSummary"] = alerting.summary(db, scope)
    return ok(data)
