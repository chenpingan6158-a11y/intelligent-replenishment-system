# 连锁餐饮门店订货与库存智能补货系统

《高级软件工程》项目实践 · 题目 30。基于 **Python (FastAPI)** 的全栈 Web 系统：门店端一键订货、总部端智能补货，覆盖库存批次效期（FEFO）、审批流、预警与经营看板。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / Pydantic v2 |
| 数据库 | SQLite（默认，零配置；可通过 `DATABASE_URL` 切换 MySQL/PostgreSQL） |
| 前端 | 原生 HTML/CSS/JS 单页应用（无构建步骤、无 CDN 依赖，离线可运行） |
| 认证 | JWT（HS256，标准库实现）+ PBKDF2 口令散列 + RBAC 数据权限 |
| 测试 | pytest（43 个用例：预测引擎 / 库存 FEFO / 状态机 / 审批规则） |

## 一键启动

```bash
pip install -r requirements.txt
python run.py                 # 首次启动自动建库并生成演示数据
```

打开：

- 系统界面：<http://127.0.0.1:8000/>
- 接口文档：<http://127.0.0.1:8000/docs>

演示账号（首次启动自动创建）：

| 账号 | 口令 | 角色 |
|---|---|---|
| sm001 | sm123 | 门店店长（南京东路店） |
| clerk001 | clerk123 | 门店员工 |
| region_east | region123 | 华东区域经理 |
| hq | hq123 | 总部供应链计划员 |
| wh | wh123 | 中央厨房 |
| admin | admin123 | 系统管理员 |

重建演示数据：`python run.py --reseed`

## Docker / Codespaces 启动（课程要求的环境复现）

```bash
docker compose up --build
# 或在 GitHub Codespaces 中直接打开仓库，容器内执行 python run.py
```

## 核心业务闭环

```
智能补货建议（可解释明细）
      │ 店长确认/调整 → 生成订货单
      ▼
DRAFT → SUBMITTED → APPROVED → CONFIRMED(发货) → RECEIVED → CLOSED
              │                        │
              └─ 命中免审规则自动通过    └─ 门店收货：按实收入库，差异自动登记
```

审批触发条件（BR-07）：订单金额 > 500 元，或订货量偏离建议量 > 50%，或超出最大库存约束。

## 关键设计

1. **BR-01 单位换算**：库存一律以最小计量单位（克/毫升/个）整数存储，录入与展示按 `unit_conversion` 换算，支持小数订货（如 1.5 箱），杜绝浮点误差。
2. **BR-03 FEFO 出库**：先到期先出，同效期按入库先后；批次效期自动生成临期预警。
3. **BR-05 乐观锁**：库存扣减带版本号，冲突重试，防并发超卖。
4. **智能补货算法**（`app/services/forecast.py`，纯函数可单测）：
   `基线需求 × 星期因子 × 趋势修正 → 提前期需求 μ_L → 安全库存 Z·σ·√L → 补货点 ROP → 建议量按 MOQ/整箱取整`，数据不足 14 天自动冷启动降级，输出完整推导明细。
5. **可解释建议**：每条建议展示「现存/在途/覆盖期需求/安全库存/补货点」与计算公式，店长可理解、可兜底。

## 目录结构

```
├── run.py                  # 一键启动
├── app/
│   ├── main.py             # FastAPI 入口（自动建库 + 灌数据）
│   ├── models.py           # 全部数据模型（含 BR-01/03/04 设计注释）
│   ├── security.py         # JWT + PBKDF2
│   ├── deps.py             # 登录态 / RBAC / 门店数据权限
│   ├── schemas.py          # 请求体模型
│   ├── seed.py             # 演示数据生成器
│   ├── services/           # 业务层：forecast（算法）/ inventory / ordering / alerting / metrics / units
│   └── routers/            # API 层：auth / master / inventory / replenishment / orders / dashboard
├── web/                    # 前端单页应用（index.html + css + js）
├── tests/                  # pytest 单元测试（43 例）
└── docs/                   # 课程文档（计划书等）
```

## 测试

```bash
python -m pytest tests/ -v
```

覆盖：预测引擎（星期因子 / 冷启动 / MOQ 与整箱取整 / 安全库存 / 回测）、库存（单位换算 / FEFO / 盘点 / 乐观锁 / 负库存拒绝）、订货（状态机非法流转 / 审批阈值 / 偏离度 / 部分收货差异）。

## 两阶段划分说明（与课程流程的衔接）

**阶段一（当前，代码实现）**：先完成可运行、可验证的 Web 系统——所有业务规则先在代码与测试中坐实，形成"事实上的需求基线"。

**阶段二（下一步，流程图绘制）**：以阶段一的真实实现为依据，反向整理并绘制 UML 模型（业务用例图、活动图、系统用例图、按用例的类图与顺序图、ER 图）。

两阶段的衔接方式：

1. 阶段一代码中的**状态机（`ordering.TRANSITIONS`）、业务规则（BR-01~BR-10）、算法公式**直接成为阶段二顺序图/活动图的绘制素材，保证"图与系统一致"，避免先画图后实现常见的图码不符；
2. 阶段二绘制时若发现模型缺陷（如缺少异常分支），回到阶段一代码修正并补充测试，形成"代码 ↔ 模型"双向校验闭环；
3. 所有图的源文件与导出图统一入库 `docs/uml/`，与报告章节一一对应。

## API 概览

| 前缀 | 说明 |
|---|---|
| `/api/auth` | 登录、当前用户、演示账号 |
| `/api/master` | 区域、门店、分类、商品、单位换算、补货策略、配方、账号 |
| `/api/inventory` | 库存查询、批次效期、流水、入库、出库、报损、盘点、调拨 |
| `/api/replenishment` | 补货建议（含明细）、消耗曲线、滚动回测 |
| `/api/orders` | 订货单创建/提交/审批/发货/收货/取消 |
| `/api/alerts` | 预警列表、扫描、处理 |
| `/api/dashboard` | 经营看板指标（缺货率、周转、损耗率、达成率） |
