"""从 SQLAlchemy 元数据生成 ER 图（PlantUML 源码）。

这样画出来的 ER 图与 app/models.py 永远一致：改了模型重跑本脚本即可。
用法：python gen_er.py  → 输出 docs/uml/13-ER图.puml
"""
from __future__ import annotations

import io
import pathlib

from app.database import Base
import app.models  # noqa: F401  确保模型被注册到 metadata

OUT = pathlib.Path("docs/uml/13-ER图.puml")

# 按业务域分组，便于阅读；未列出的表落到「其他」
DOMAINS: dict[str, list[str]] = {
    "组织与权限": ["region", "store", "app_user"],
    "商品与菜谱": ["category", "product", "unit_conversion", "recipe", "recipe_item"],
    "库存与批次": ["stock", "stock_batch", "stock_movement"],
    "盘点与调拨": ["stocktake_order", "stocktake_item", "transfer_order"],
    "销量与消耗": ["sales_daily", "consumption_daily"],
    "补货策略": ["replenishment_policy"],
    "订货与审批": ["purchase_order", "purchase_order_item", "approval_record"],
    "预警与审计": ["alert", "operation_log"],
}

# 表名 → 中文注释
LABELS = {
    "region": "区域",
    "store": "门店",
    "app_user": "用户",
    "category": "商品分类",
    "product": "商品",
    "unit_conversion": "单位换算",
    "recipe": "菜谱",
    "recipe_item": "菜谱用料",
    "stock": "库存",
    "stock_batch": "库存批次",
    "stock_movement": "库存流水",
    "stocktake_order": "盘点单",
    "stocktake_item": "盘点明细",
    "transfer_order": "调拨单",
    "sales_daily": "日销量",
    "consumption_daily": "日消耗",
    "replenishment_policy": "补货策略",
    "purchase_order": "订货单",
    "purchase_order_item": "订货明细",
    "approval_record": "审批记录",
    "alert": "预警",
    "operation_log": "操作日志",
}

TYPE_MAP = {
    "INTEGER": "int",
    "VARCHAR": "varchar",
    "DATETIME": "datetime",
    "DATE": "date",
    "BOOLEAN": "bool",
    "TEXT": "text",
    "FLOAT": "float",
    "NUMERIC": "decimal",
}


def short_type(col) -> str:
    """把 SQLAlchemy 类型压成紧凑写法：VARCHAR(50) -> varchar(50)。"""
    raw = str(col.type).upper()
    for full, short in TYPE_MAP.items():
        if raw.startswith(full):
            return short + raw[len(full):].lower()
    return raw.lower()


def main() -> None:
    tables = Base.metadata.tables
    # 表名 → 别名（PlantUML 标识符）
    alias = {name: f"t_{name}" for name in tables}

    lines: list[str] = [
        "@startuml",
        "skinparam backgroundColor #FFFFFF",
        "skinparam linetype ortho",
        "skinparam arrowColor #666666",
        "hide circle",
    ]

    placed: set[str] = set()
    for domain, names in DOMAINS.items():
        present = [n for n in names if n in tables]
        if not present:
            continue
        lines.append(f'package "{domain}" {{')
        for name in present:
            table = tables[name]
            placed.add(name)
            lines.append(f'  entity "{name} {LABELS.get(name, "")}" as {alias[name]} {{')
            for col in table.columns:
                marks = []
                if col.primary_key:
                    marks.append("<<PK>>")
                if col.foreign_keys:
                    marks.append("<<FK>>")
                nullable = "" if (col.primary_key or not col.nullable) else " ?"
                mark = (" " + " ".join(marks)) if marks else ""
                lines.append(f"    {col.name} : {short_type(col)}{nullable}{mark}")
            lines.append("  }")
        lines.append("}")

    # 兜底：未归类的表
    leftovers = [n for n in tables if n not in placed]
    if leftovers:
        lines.append('package "其他" {')
        for name in leftovers:
            table = tables[name]
            lines.append(f'  entity "{name}" as {alias[name]} {{')
            for col in table.columns:
                lines.append(f"    {col.name} : {short_type(col)}")
            lines.append("  }")
        lines.append("}")

    lines.append("")

    # 关系：以 FK 为准，父表 ||--o{ 子表，标注外键字段名
    seen: set[tuple[str, str, str]] = set()
    for name, table in sorted(tables.items()):
        for col in table.columns:
            for fk in col.foreign_keys:
                parent = fk.column.table.name
                key = (parent, name, col.name)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"{alias[parent]} ||--o{{ {alias[name]} : {col.name}"
                )

    lines.append("@enduml")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成 {OUT}：{len(tables)} 张表，{len(seen)} 条外键关系")


if __name__ == "__main__":
    main()
