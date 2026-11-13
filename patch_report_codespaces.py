# -*- coding: utf-8 -*-
"""附录3 Codespaces 收尾：更新提交数说明、替换图A-1、新增图A-2/A-3，6.2 加验证说明。

每次运行先从本脚本自己的备份恢复（仅含上一次运行结果），再重新应用修改。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm

BASE = Path(__file__).resolve().parent
DOC = BASE / "docs" / "项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx"
BAK = BASE / ".backup" / "项目实践报告-Codespaces前备份.docx"
SHOT_DIR = BASE / "docs" / "screenshots"

SHOT_COMMITS = SHOT_DIR / "14-GitHub提交记录.png"
SHOT_TEST = SHOT_DIR / "15-Codespaces云端测试.png"
SHOT_RUN = SHOT_DIR / "16-Codespaces运行页面.png"

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def backup() -> None:
    BAK.parent.mkdir(exist_ok=True)
    if not BAK.exists():
        shutil.copy2(DOC, BAK)
    else:
        shutil.copy2(BAK, DOC)


def replace_text(p, new_text: str) -> None:
    """清空段落所有 run，把新文本写进第一个 run（沿用其样式）。"""
    runs = p.runs
    if not runs:
        p.add_run(new_text)
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""


def picture_in(p):
    blips = p._p.findall(".//" + qn("a:blip"))
    return blips[0] if blips else None


def replace_picture(doc, p, image_path: Path) -> None:
    """原位替换段落中的图片二进制（保持尺寸与图注不变）。"""
    blip = picture_in(p)
    if blip is None:
        raise SystemExit(f"段落无图片: {p.text[:30]}")
    rId = blip.get(qn("r:embed"))
    part = doc.part.related_parts[rId]
    with open(image_path, "rb") as f:
        part._blob = f.read()


def add_para(doc, text: str = "", style: str | None = None):
    p = doc.add_paragraph(style=style)
    if text:
        p.add_run(text)
    return p


def add_pic(doc, image_path: Path, width_cm: float = 15.0):
    p = doc.add_paragraph()
    p.alignment = 1  # 居中
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))
    return p


def main() -> None:
    backup()
    doc = Document(str(DOC))

    # ---- 附录 3 ----
    paras = doc.paragraphs
    idx = {i: p for i, p in enumerate(paras)}

    # 1. 提交记录说明 5 次 -> 8 次（含 Codespaces 2 次）
    p238 = idx[238]
    replace_text(p238, (
        "提交记录截图：仓库 main 分支共 8 次提交，时间线连续、信息规范；"
        "其中「test: 补充补货算法边界用例与 RBAC 权限越权用例」与"
        "「docs: 报告补充 GitHub Copilot 参与记录并更新实测版本号」两次提交"
        "对应附录 2 中 Copilot 参与的测试补全与文档更新工作；"
        "「fix: 补充 pytest 配置…」与「chore: devcontainer 镜像升级至 Python 3.13…」"
        "两次提交在 GitHub Codespaces 云端完成（提交时间为 UTC，即 Codespaces 使用痕迹）。"
    ))

    # 2. 原位替换图 A-1（旧提交记录截图 -> 新 8 条截图）
    replace_picture(doc, idx[239], SHOT_COMMITS)
    replace_text(idx[240], "图 A-1 仓库提交历史（GitHub Commits 页面截图，共 8 次提交）")

    # 3. 追加 Codespaces 验证段 + 图 A-2 / 图 A-3
    add_para(doc, (
        "开发环境验证（GitHub Codespaces）：项目在 Codespaces 云端容器（Python 3.13 镜像）"
        "中完成依赖安装与测试验证——56 个用例全部通过；并通过端口转发在浏览器中"
        "访问系统首页，验证云端环境可完整运行。此外，devcontainer 镜像由 3.11 升级至 3.13、"
        "新增 pytest.ini 修复模块导入路径两项改动均在 Codespaces 内完成并提交。"
    ))
    add_pic(doc, SHOT_TEST)
    add_para(doc, "图 A-2 GitHub Codespaces 云端运行 pytest（56 个用例全部通过）")
    add_pic(doc, SHOT_RUN)
    add_para(doc, "图 A-3 Codespaces 端口转发访问系统登录页（app.github.dev 域名）")

    # ---- 6.2 补充一句云端验证说明 ----
    for p in doc.paragraphs:
        if p.text.startswith("AI 补充用例的质量控制"):
            tail = doc.paragraphs  # 重新取（避免引用失效）
            # 在该段落之后插入：找到它的下一个段落，用 insert_paragraph_before
            anchor = None
            seen = False
            for pp in tail:
                if seen:
                    anchor = pp
                    break
                if pp._p is p._p:  # 按底层 XML 元素比较， Paragraph 包装对象每次重新创建
                    seen = True
            new_p = (anchor.insert_paragraph_before if anchor is not None
                     else doc.add_paragraph)()
            if new_p is None:
                new_p = doc.add_paragraph()
            new_p.add_run(
                "上述测试同步在 GitHub Codespaces 云端容器（Python 3.13）中复跑，"
                "56 个用例全部通过，验证了代码对环境的可移植性（截图见附录 3 图 A-2）。"
            )
            break

    doc.save(str(DOC))
    print("完成：图A-1已替换，图A-2/A-3已追加，提交数说明已更新，6.2已补云端验证说明。")


if __name__ == "__main__":
    main()
