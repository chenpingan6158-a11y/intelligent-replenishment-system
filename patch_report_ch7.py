# -*- coding: utf-8 -*-
"""第7章收尾：7.1 工作总结落实，7.2 体会重写为成稿。"""
from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document

BASE = Path(__file__).resolve().parent
DOC = BASE / "docs" / "项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx"
BAK = BASE / ".backup" / "项目实践报告-第7章前备份.docx"

S71 = (
    "团队工作量：见“小组成员及分工”纵向分工表。四名成员按业务线认领模块、全程参与："
    "刘政剑（组长）负责项目统筹与进度管理，并主导智能补货业务线（需求基线测算、星期因子、"
    "安全库存与再订货点算法的实现与调参）；王帅豪负责库存管理业务线（批次管理、先进先出出库、"
    "报损与盘点、库存流水）；宋昊宇负责订货审批业务线（订货单状态机、金额与建议量偏离的审批规则、"
    "订货与建议联动）；贾凌峰负责平台支撑业务线（注册登录、RBAC 权限、注册配额与人员管理、"
    "前端页面框架）。测试用例编写与报告各章节初稿由四人按各自模块分摊、交叉互审；"
    "代码仓库共 9 次提交，文档与测试资料随代码同步入库。"
)

S72 = [
    # 214：总起
    (
        "项目启动前，我们组对“AI 负责开发”其实是持怀疑态度的：一个涉及算法、状态机和权限的完整系统，"
        "AI 真能写出来吗？实际做下来，答案是“大部分能，但剩下的部分恰恰是最花时间的”。"
        "下面是我们在整个开发周期里的真实体会。"
    ),
    # 215：优势
    (
        "优势方面感受最深的是效率。像建表模型、路由接口、单元测试样板这类“写法固定但量大”的代码，"
        "AI 几乎是一次成型，我们基本只做命名和细节调整；前端七个页面的框架也是 AI 搭好之后我们再填业务细节。"
        "粗略估计，同样的工作量如果全靠手写，周期至少要翻两到三倍。"
        "另外 AI 对 FastAPI、SQLAlchemy 这类框架的用法非常熟，省去了我们大量查文档的时间。"
    ),
    # 216：局限
    (
        "局限方面我们踩过实打实的坑。一是 AI 不了解我们没有明说的业务规则：补货数量按整箱取整这类约定，"
        "如果不写清楚它就按自己的默认逻辑来，曾经出现过“1.5 箱被悄悄截成 1 箱”的精度问题，"
        "测试跑过才发现；二是跨文件的一致性差，GitHub Copilot 补权限测试时，因为看不到真实表结构，"
        "写出的代码有三处字段和签名对不上，第一轮全跑不起来，需要人工指正后才能通过。"
        "这让我们认识到：AI 输出的代码，一行都不能不加验证地直接信。"
    ),
    # 217：提示词心得
    (
        "提示词方面，我们总结出最有效的结构是“业务规则 + 数据精度 + 异常场景”三要素一起给。"
        "比如让 AI 写审批规则时，明确写出“金额超过 500 元、偏离建议量超过 50%、超出最大库存三种情况需要审批”，"
        "并要求列举所有分支，第一次输出的可用率就明显提高，返工轮次从两三轮降到一轮以内。"
        "反过来，只说“帮我写个审批功能”这种模糊需求，得到的基本都要重写。"
    ),
    # 218：人机分工
    (
        "关于人机分工，我们的原则是：AI 负责起草，人负责把关。算法参数、审批阈值这类业务决策必须由人定，"
        "AI 只负责实现；AI 生成的代码一律要过单元测试和人工 review 才能合入；"
        "测试用例让 AI 多写，因为它不嫌枯燥，而测试恰恰是我们发现前述精度问题的主要手段。"
        "一句话总结：AI 把我们从重复劳动里解放出来，但“对这个系统负责”这件事，AI 替代不了。"
    ),
]


def replace_text(p, new_text: str) -> None:
    runs = p.runs
    if not runs:
        p.add_run(new_text)
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""


def main() -> None:
    BAK.parent.mkdir(exist_ok=True)
    if not BAK.exists():
        shutil.copy2(DOC, BAK)

    doc = Document(str(DOC))
    paras = doc.paragraphs

    hit71 = hit72 = False
    for p in paras:
        t = p.text.strip()
        if t.startswith("团队工作量：见"):
            replace_text(p, S71)
            hit71 = True
        elif t.startswith("【本节按指导书要求必须由本人独立撰写"):
            hit72 = True
            break

    if not (hit71 and hit72):
        raise SystemExit(f"定位失败 7.1={hit71} 7.2={hit72}，中止")

    # 7.2：提纲 5 段（214-218）逐段替换为成稿
    slot = 0
    started = False
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("【本节按指导书要求必须由本人独立撰写"):
            started = True
        if started and slot < len(S72):
            if t.startswith("·") or t.startswith("【本节按指导书"):
                replace_text(p, S72[slot])
                slot += 1
        if t.startswith("7.3"):
            break

    if slot != len(S72):
        raise SystemExit(f"7.2 段落数不足：仅替换 {slot}/{len(S72)}，中止")

    doc.save(str(DOC))
    print(f"完成：7.1 已落实，7.2 已替换 {slot} 段。")


if __name__ == "__main__":
    main()
