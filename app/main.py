"""应用入口。

启动方式：
    python run.py            # 推荐，自动建库 + 灌演示数据 + 起服务
    uvicorn app.main:app --reload
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .config import APP_NAME, APP_VERSION
from .database import SessionLocal, init_db
from .models import Product
from .routers import auth, dashboard, inventory, master, orders, replenishment

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title=APP_NAME, version=APP_VERSION, description="连锁餐饮门店订货与库存智能补货系统 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "请求参数"
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": f"参数校验失败：{field} {first.get('msg', '')}", "data": None},
    )


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        count = db.execute(select(func.count(Product.id))).scalar() or 0
    finally:
        db.close()
    if count == 0:
        from .seed import seed

        print("[startup] 检测到空库，正在生成演示数据…")
        seed()


app.include_router(auth.router)
app.include_router(master.router)
app.include_router(inventory.router)
app.include_router(replenishment.router)
app.include_router(orders.router)
app.include_router(dashboard.router)


@app.get("/api/health", tags=["系统"])
def health():
    return {"code": 0, "message": "ok", "data": {"app": APP_NAME, "version": APP_VERSION}}


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"code": 0, "message": "前端文件缺失，请访问 /docs 查看接口文档", "data": None})
