"""在现有报告 docx 上原地补充 GitHub Copilot 参与记录。

定位方式：表格按索引、段落按文字内容锚点，避免插入段落后索引漂移。
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph

DOC = Path("docs/项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx")
BAK = Path(".backup/项目实践报告-改前备份.docx")


def set_cell(cell, text: str) -> None:
    p = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r.text = ""
    else:
        p.add_run(text)


def set_para(p, text: str) -> None:
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r.text = ""
    else:
        p.add_run(text)


def find_para(doc, fragment: str) -> Paragraph:
    for p in doc.paragraphs:
        if fragment in p.text:
            return p
    raise LookupError(f"未找到包含「{fragment}」的段落")


def clone_para_after(p, text: str) -> Paragraph:
    new_el = copy.deepcopy(p._element)
    p._element.addnext(new_el)
    np = Paragraph(new_el, p._parent)
    set_para(np, text)
    return np


def clone_row_after(table, row_idx: int):
    new_tr = copy.deepcopy(table.rows[row_idx]._tr)
    table.rows[row_idx]._tr.addnext(new_tr)
    return table.rows[row_idx + 1]


def main() -> None:
    if not BAK.exists():
        raise SystemExit("备份不存在，请先确认")
    shutil.copy2(BAK, DOC)  # 从改前备份还原，保证可重复执行
    doc = Document(str(DOC))
    log: list[str] = []

    # ---------- 表 5-1 ----------
    t51 = doc.tables[12]
    set_cell(t51.rows[1].cells[1], "WorkBuddy 智能体（主体开发）；GitHub Copilot（测试补全 / 代码审查 / 文档生成）")
    set_cell(t51.rows[1].cells[2], "WorkBuddy 桌面版；Copilot Free（VS Code 扩展）")
    set_cell(t51.rows[2].cells[1], "VS Code")
    set_cell(t51.rows[2].cells[2], "1.145.2（x64）")
    set_cell(t51.rows[3].cells[2], "Python 3.13.14 / FastAPI 0.162.4 / Uvicorn 0.54.0")
    set_cell(t51.rows[4].cells[2], "SQLAlchemy 2.1.8 / SQLite 3.x（可迁移 MySQL）")
    set_cell(t51.rows[7].cells[1], "pytest（内存 SQLite 夹具，领域层单测）")
    set_cell(t51.rows[7].cells[2], "pytest 9.2.0，56 个用例")
    log.append("表5-1：AI 工具/IDE/框架/测试版本全部落实，2 处【待填写】已填")

    # ---------- 6.1 ----------
    p = find_para(doc, "测试环境：Windows 11")
    set_para(
        p,
        "测试环境：Windows 11 / Python 3.13.14 / SQLite；测试框架 pytest 9.2.0，"
        "测试夹具为内存 SQLite（sqlite:// + StaticPool），直接调用领域服务与权限依赖函数，"
        "不启动 HTTP 服务；界面验证采用 Chrome 无头浏览器截图。测试方法覆盖三层："
        "单元测试（预测引擎、库存域、订货域、权限层）、全链路人工集成验证"
        "（登录—建议—下单—审批—发货—收货—对账）、界面冒烟测试（7 个页面截图人工审查）。"
        "准入条件：单元测试全部通过且代码可启动；准出条件：56 个测试用例 100% 通过、"
        "全链路集成对账（收货后库存增加量与订货量精确相等）。",
    )
    log.append("6.1：测试框架改为 pytest 9.2.0 + 内存 SQLite 夹具，用例数 43 → 56")

    # ---------- 表 6-1 ----------
    t61 = doc.tables[13]
    set_cell(t61.rows[1].cells[1], "18")
    set_cell(
        t61.rows[1].cells[2],
        "基线/星期因子/趋势/安全库存/ROP/建议量取整/冷启动降级/单日历史/全零消耗/首尾日期不齐",
    )
    row = clone_row_after(t61, 3)
    set_cell(row.cells[0], "权限层（test_permissions.py）")
    set_cell(row.cells[1], "10")
    set_cell(row.cells[2], "角色守卫拒绝/放行、门店与大区数据范围隔离、跨店越权 403、未绑定门店 400")
    set_cell(row.cells[3], "100%")
    t61 = doc.tables[13]
    set_cell(t61.rows[5].cells[0], "全链路人工验证（非 pytest）")
    set_cell(t61.rows[5].cells[1], "—")
    set_cell(t61.rows[5].cells[2], "登录→建议→下单→审批→发货→收货→对账，核对收货后库存增加量与订货量")
    set_cell(t61.rows[5].cells[3], "通过")
    log.append("表6-1：预测引擎 15→18，新增权限层 10 例，接口集成行改为人工全链路验证")

    # ---------- 6.2 新增一段 ----------
    anchor = find_para(doc, "重点用例执行记录")
    clone_para_after(
        anchor,
        "AI 补充用例的质量控制：测试阶段后期由 GitHub Copilot 依据既有测试风格补充 13 个用例——"
        "其中 3 个补货算法边界用例（单日历史、连续 14 天全零消耗、首尾日期不齐）一次通过；"
        "10 个 RBAC 越权用例首轮生成时存在 3 处与实际实现不符的错误（Region / Store 漏写必填 code 字段、"
        "allowed_store_ids 调用漏传 db 参数），经人工核对表结构与函数签名后修正，全部通过。"
        "结论：AI 能高效产出用例结构与断言骨架，但字段级、签名级事实必须由人核对交付物。",
    )
    log.append("6.2：新增一段，说明 Copilot 补充 13 个用例及 3 处错误的修正过程")

    # ---------- 6.4 结论二 ----------
    p = find_para(doc, "结论二：")
    set_para(
        p,
        "结论二：单元测试先行的开发顺序让人机协作质量可控：56 个测试（含 AI 补充的 13 个）"
        "在编码与测试阶段抓出 4 个严重缺陷（含 1 个静默截断与 1 个重构误删），"
        "全部在集成前闭环，未流入演示环境。",
    )
    log.append("6.4 结论二：43 → 56，并注明含 AI 补充的 13 个")

    # ---------- 表 6-3 ----------
    t63 = doc.tables[15]
    set_cell(t63.rows[1].cells[1], "约 7,877 行（后端 4,283 / 前端 2,922 / 测试 672）")
    log.append("表6-3：代码总规模 7,750 → 7,877 行")

    # ---------- 表 7-1 ----------
    t71 = doc.tables[16]
    set_cell(t71.rows[6].cells[2], "56 个用例 100% 通过（含 Copilot 补充的 13 个）")
    log.append("表7-1：自动化测试 43 → 56")

    # ---------- 表 A-1 ----------
    ta1 = doc.tables[17]
    set_cell(ta1.rows[7].cells[0], "测试 tests/*（4 个文件）")
    set_cell(ta1.rows[7].cells[1], "672 行")
    set_cell(ta1.rows[7].cells[2], "约 30%（其中 13 个用例由 Copilot 生成）")
    set_cell(
        ta1.rows[7].cells[3],
        "补充回归用例（1.5 箱、驳回重提、区域归属）；Copilot 补充边界与越权用例 13 个，"
        "修正字段/签名错误 3 处",
    )
    set_cell(ta1.rows[9].cells[1], "≈ 7,877 行")
    set_cell(ta1.rows[9].cells[3], "56 个测试用例全部通过")
    log.append("表A-1：测试行 4 个文件/672 行，标注 Copilot 生成 13 例；合计 56")

    # ---------- 表 A-2 ----------
    ta2 = doc.tables[18]
    row = clone_row_after(ta2, 5)
    set_cell(row.cells[0], "权限越权测试（Copilot）")
    set_cell(
        row.cells[1],
        "“参照 test_orders.py 的 fixture 风格，为 RBAC 权限层补充越权用例，断言 403/400，"
        "不引入 HTTP 客户端，只新增测试文件不改源码……”",
    )
    set_cell(
        row.cells[2],
        "结构一次成型、断言分布合理；但 3 处字段/签名与实际实现不符（Region/Store 缺 code、"
        "漏传 db），指正 1 轮后全部通过",
    )
    log.append("表A-2：新增 1 行 Copilot 权限测试提示词记录")

    # ---------- 附录 3 ----------
    p = find_para(doc, "本项目代码与文档托管于 GitHub")
    set_para(
        p,
        "本项目代码与文档托管于 GitHub，仓库地址："
        "https://github.com/chenpingan6158-a11y/intelligent-replenishment-system。",
    )
    clone_para_after(
        p,
        "GitHub Copilot 使用记录：项目功能实现完成后引入 Copilot 参与测试补全与代码审查，"
        "产出 tests/test_forecast.py 边界用例 3 个、tests/test_permissions.py 越权用例 10 个；"
        "使用过程、提示词与人工指正记录见附录 2，相关提交见仓库提交历史。",
    )
    log.append("附录3：填入仓库地址，新增 Copilot 使用记录段（在正文段之后，标题未被触碰）")

    doc.save(str(DOC))
    print("已保存：", DOC)
    for i, s in enumerate(log, 1):
        print(f"  {i}. {s}")


if __name__ == "__main__":
    main()
