# skill_manager.py
# -*- coding: utf-8 -*-
"""Skill 系统（对标 AnySpark 的技能机制）。

用法：
- skills/ 目录下每个 .md 文件即一个"技能"（写作技法、流派脚手架、文风指南等）。
- 在 config.json 的 reference_settings.active_skills 中列出要启用的技能名（不含 .md 后缀）。
- 生成时由 reference_manager.get_generation_context_block() 把启用技能的内容拼进 prompt。
- 想新增技能：往 skills/ 目录丢一个 .md 文件即可，无需改任何代码。
"""
import os
import logging

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def list_skills() -> list:
    """列出所有可用技能名（不含 .md 后缀），按字母序返回。"""
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(f[:-3] for f in os.listdir(SKILLS_DIR) if f.endswith(".md"))


def get_skill_text(name: str) -> str:
    """读取单个技能文件内容，不存在或读失败返回空串。"""
    # 防路径穿越：技能名不允许包含路径分隔符
    if not name or os.sep in name or "/" in name:
        return ""
    path = os.path.join(SKILLS_DIR, name + ".md")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"读取技能文件失败: {name} -> {e}")
        return ""


def get_active_skills_text(active_names) -> str:
    """把启用的技能拼接为一个可注入 prompt 的文本块，无启用技能时返回空串。"""
    blocks = []
    for n in active_names or []:
        t = get_skill_text(n)
        if t.strip():
            blocks.append(f"【启用技能：{n}】\n{t.strip()}")
    if not blocks:
        return ""
    return "\n\n".join(blocks)
