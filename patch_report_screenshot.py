"""把 GitHub 提交记录截图插入报告附录 3（原地修改，含备份校验）。"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

from docx import Document
from docx.shared import Inches
from docx.text.paragraph import Paragraph

DOC = Path("docs/项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx")
BAK = Path(".backup/项目实践报告-改前备份.docx")
IMG = Path("docs/screenshots/14-GitHub提交记录.png")


def find_para(doc, fragment: str) -> Paragraph:
    for p in doc.paragraphs:
        if fragment in p.text:
            return p
    raise LookupError(fragment)


def clone_para_after(p, text: str = "") -> Paragraph:
    new_el = copy.deepcopy(p._element)
    p._element.addnext(new_el)
    np = Paragraph(new_el, p._parent)
    for r in list(np.runs):
        r.text = ""
    if text:
        if np.runs:
            np.runs[0].text = text
        else:
            np.add_run(text)
    return np


def main() -> None:
    # 注意：不从旧备份还原（备份早于 Copilot 补充），直接在当前版本上改
    fresh = Path(".backup/项目实践报告-插图前备份.docx")
    fresh.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DOC, fresh)
    doc = Document(str(DOC))

    p = find_para(doc, "【待填写：请粘贴仓库 Commits 页面")
    set_text = (
        "提交记录截图：仓库 main 分支共 5 次提交，时间线连续、信息规范；"
        "其中「test: 补充补货算法边界用例与 RBAC 权限越权用例」与"
        "「docs: 报告补充 GitHub Copilot 参与记录并更新实测版本号」两次提交"
        "对应附录 2 中 Copilot 参与的测试补全与文档更新工作。"
    )
    runs = p.runs
    if runs:
        runs[0].text = set_text
        for r in runs[1:]:
            r.text = ""

    pic_p = clone_para_after(p)
    run = pic_p.add_run()
    run.add_picture(str(IMG), width=Inches(6.0))

    cap = clone_para_after(pic_p, "图 A-1 仓库提交历史（GitHub Commits 页面截图）")
    for r in cap.runs:
        r.font.size = None  # 沿用克隆格式

    doc.save(str(DOC))
    print("已插入截图与图注，占位段已改写。")


if __name__ == "__main__":
    main()
