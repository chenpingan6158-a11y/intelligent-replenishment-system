"""一键启动脚本。

    python run.py            # 默认 127.0.0.1:8000
    python run.py --port 9000 --host 0.0.0.0
    python run.py --reseed   # 清空并重建演示数据
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="启动连锁餐饮智能补货系统")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--reseed", action="store_true", help="清空数据库并重建演示数据")
    args = parser.parse_args()

    from app.database import init_db

    init_db()

    if args.reseed:
        from app.seed import seed

        seed(force=True)

    import uvicorn

    print("=" * 68)
    print("  连锁餐饮门店订货与库存智能补货系统")
    print(f"  界面： http://{args.host}:{args.port}/")
    print(f"  接口： http://{args.host}:{args.port}/docs")
    print("  演示账号：sm001 / sm123（店长）  hq / hq123（总部）  wh / wh123（中央厨房）")
    print("=" * 68)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    sys.path.insert(0, ".")
    main()
