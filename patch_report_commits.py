# -*- coding: utf-8 -*-
"""替换附录 3 图 A-1 为最新 Commits 截图（16 次提交、四名成员可见），并同步更新文字。"""
import shutil
from docx import Document
from docx.shared import Emu

DOC = "docs/项目实践报告-连锁餐饮门店订货与库存智能补货系统.docx"
BAK = ".backup/项目实践报告-图A1替换前备份.docx"
IMG = "docs/screenshots/14-GitHub提交记录.png"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

def set_text(paragraph, text):
    """保留段落第一个 run 的格式，重写文字。"""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)

def main():
    shutil.copy2(DOC, BAK)
    doc = Document(DOC)
    paras = doc.paragraphs

    # 定位：图 A-1 图注段
    cap_idx = next(i for i, p in enumerate(paras) if p.text.strip().startswith("图 A-1"))
    img_idx = cap_idx - 1
    img_para = paras[img_idx]
    if not img_para._p.findall(f".//{NS_A}blip"):
        raise SystemExit(f"段 {img_idx} 不含图片，中止")

    # 取旧图宽度，保持版式一致
    blip_extent = img_para._p.find(f".//{NS_A}ext")
    old_w = int(blip_extent.get("cx")) if blip_extent is not None else 5486400

    # 删除旧图的所有 run，插入新图（只给宽度，高度按比例自动）
    for r in list(img_para.runs):
        r._r.getparent().remove(r._r)
    img_para.add_run().add_picture(IMG, width=Emu(old_w))

    # 更新图注与说明文字
    set_text(paras[cap_idx], "图 A-1 仓库提交历史（GitHub Commits 页面截图，共 16 次提交）")

    desc_idx = next(
        i for i, p in enumerate(paras) if p.text.strip().startswith("提交记录截图")
    )
    set_text(
        paras[desc_idx],
        "提交记录截图：仓库 main 分支共 16 次提交，时间线连续、信息规范，四名成员的提交均可见"
        "（刘政剑 chenpingan6158-a11y、王帅豪 wsh-dotcommer、宋昊宇 Yuuu2026、贾凌峰 joyful-2029）；"
        "其中「test: 补充补货算法边界用例与 RBAC 权限越权用例」与「docs: 报告补充 GitHub Copilot 参与记录"
        "并更新实测版本号」两次提交对应附录 2 中 Copilot 参与的测试补全与文档更新工作；"
        "「fix: 补充 pytest 配置…」与「chore: devcontainer 镜像升级至 Python 3.13…」两次提交在"
        " GitHub Codespaces 云端完成（提交时间为 UTC，即 Codespaces 使用痕迹）。",
    )

    doc.save(DOC)
    print(f"完成：图 A-1 已替换（宽度 {old_w} EMU），图注与说明已更新")
    print(f"备份：{BAK}")

if __name__ == "__main__":
    main()
