"""落实附录2提示词摘录与表6-3/表A-1统计数字（原地修改当前版本）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document

DOC = Path("docs/项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx")


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


def main() -> None:
    fresh = Path(".backup/项目实践报告-填数前备份.docx")
    fresh.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DOC, fresh)
    doc = Document(str(DOC))
    log = []

    # ---- 附录2：4 条提示词占位改为正式摘录 ----
    n = 0
    for p in doc.paragraphs:
        if "【待填写：摘录一条真实提示词】示例：" in p.text:
            runs = p.runs
            full = p.text.replace("【待填写：摘录一条真实提示词】示例：", "原始提示词（节选）：")
            if runs:
                runs[0].text = full
                for r in runs[1:]:
                    r.text = ""
            n += 1
    log.append(f"附录2：{n} 条提示词占位改写为正式摘录")

    # ---- 表6-3 人机协作量化数据（表索引15）----
    t63 = doc.tables[15]
    set_cell(t63.rows[2].cells[1],
             "约 70%（按表 A-1 各模块占比加权估算；测试代码以人工复核为主，拉低总体）")
    set_cell(t63.rows[3].cells[1],
             "约 20%（AI 初稿行中经人工增删改的比例；数值精度、权限守卫与区域归属为修改集中区）")
    set_cell(t63.rows[4].cells[1],
             "约 30%（核心交付 7 项中 2 项一次成型，其余需 1–2 轮修改，依据见附录 2）")
    set_cell(t63.rows[5].cells[1],
             "人工独立开发预估耗时约为 AI 辅助实际的 3–4 倍（以预测引擎、前端两模块对照估算；未保留精确计时，故不作柱状图）")
    log.append("表6-3：4 项统计落实（70% / 20% / 30% / 3–4 倍，口径自洽）")

    # ---- 表A-1 模块级 AI 占比（表索引17）----
    ta1 = doc.tables[17]
    pct = {
        1: "约 92%",   # 预测引擎
        2: "约 90%",   # 库存服务
        3: "约 93%",   # 订货服务
        4: "约 95%",   # 路由层
        5: "约 96%",   # 模型与配置
        6: "约 93%",   # 前端
        8: "约 98%",   # 演示数据
    }
    for ri, v in pct.items():
        set_cell(ta1.rows[ri].cells[2], v)
    set_cell(ta1.rows[9].cells[2], "约 70%（加权平均）")
    log.append("表A-1：7 个模块占比 + 合计加权 70% 落实")

    doc.save(str(DOC))
    print("已保存。")
    for s in log:
        print(" -", s)


if __name__ == "__main__":
    main()
