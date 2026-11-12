"""全局配置。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_NAME = "连锁餐饮门店订货与库存智能补货系统"
APP_VERSION = "1.0.0"

# 数据库：默认 SQLite，可用 DATABASE_URL 覆盖为 MySQL/PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}")

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "chain-restock-dev-secret-change-in-production")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
JWT_ALGORITHM = "HS256"

# 业务参数（可在系统参数表中覆盖）
APPROVAL_AMOUNT_THRESHOLD_CENTS = 500_00   # 500 元
APPROVAL_DEVIATION_RATIO = 0.5             # 实订量偏离建议量 > 50% 触发审批
NEAR_EXPIRY_RATIO = 0.3                    # 剩余保质期低于 30% 触发临期预警
SLOW_MOVING_DAYS = 30                      # 周转天数超过该值判定滞销
FORECAST_HISTORY_DAYS = 28                 # 预测基线窗口

# 各角色注册人数上限（离职用户不占用名额）
# scope: global=全系统总数 / region=每个大区 / store=每个门店
REGISTER_QUOTAS = {
    "STORE_MANAGER": ("store", 2),
    "STORE_CLERK": ("store", 50),
    "REGION_MANAGER": ("region", 2),
    "HQ_PLANNER": ("global", 2),
    "WAREHOUSE": ("global", 5),
}
