# reference_manager.py
# -*- coding: utf-8 -*-
"""参考书管理（对标 AnySpark 的 get_reference_outline / detailed_outline / timeline / style 四工具）。

设计原则（最少改动）：
- 完全复用现有 RAG 基建：knowledge.advanced_split_content 分块、
  vectorstore_utils.init_vector_store / load_vector_store / get_relevant_context_from_vector_store。
- 每本参考书独立存放于 references/{书名}/ 下，与小说自身知识库隔离且只读：
    references/{书名}/vectorstore/        向量库（细节检索）
    references/{书名}/outline.md          故事大纲
    references/{书名}/detailed_outline.md 分阶段细纲
    references/{书名}/timeline.md         时间线
    references/{书名}/style.md            文风总结
- 配置存于 config.json 顶层键 reference_settings（normalize_config 不会丢弃未知键）：
    {"active_book": "龙族", "active_skills": ["爽文节奏", "悬念钩子"]}

注入入口：get_generation_context_block(flow, query, embedding_cfg)
  flow = "architecture" | "blueprint" | "chapter"
"""
import os
import re
import json
import shutil
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCES_DIR = os.path.join(BASE_DIR, "references")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

REF_MD_FILES = ("outline.md", "detailed_outline.md", "timeline.md", "style.md")

# =============== 配置读写 ===============

def load_reference_settings() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        rs = cfg.get("reference_settings") or {}
        return {
            "active_book": rs.get("active_book", ""),
            "active_skills": rs.get("active_skills", []) or [],
        }
    except Exception:
        return {"active_book": "", "active_skills": []}


def save_reference_settings(active_book=None, active_skills=None) -> bool:
    """只更新给出的字段，其余配置原样保留。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    rs = cfg.get("reference_settings") or {}
    if active_book is not None:
        rs["active_book"] = active_book
    if active_skills is not None:
        rs["active_skills"] = list(active_skills)
    cfg["reference_settings"] = rs
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logging.error(f"保存参考书配置失败: {e}")
        return False

# =============== 书库管理 ===============

def _safe_book_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", (name or "").strip())


def get_references_dir() -> str:
    os.makedirs(REFERENCES_DIR, exist_ok=True)
    return REFERENCES_DIR


def get_book_dir(name: str) -> str:
    return os.path.join(get_references_dir(), _safe_book_name(name))


def list_reference_books() -> list:
    if not os.path.isdir(REFERENCES_DIR):
        return []
    books = []
    for d in sorted(os.listdir(REFERENCES_DIR)):
        full = os.path.join(REFERENCES_DIR, d)
        if os.path.isdir(full):
            has_md = any(os.path.exists(os.path.join(full, m)) for m in REF_MD_FILES)
            has_vs = os.path.isdir(os.path.join(full, "vectorstore"))
            if has_md or has_vs:
                books.append(d)
    return books


def is_book_imported(name: str) -> bool:
    return _safe_book_name(name) in list_reference_books()


def delete_reference_book(name: str) -> bool:
    book_dir = get_book_dir(name)
    if not os.path.isdir(book_dir):
        return False
    try:
        shutil.rmtree(book_dir)
        return True
    except Exception as e:
        logging.error(f"删除参考书失败: {name} -> {e}")
        return False

# =============== 导入（向量库 + 四件套抽取） ===============

_READ_ENCODINGS = ("utf-8", "gbk", "gb2312")


def _read_text(path: str) -> str:
    for enc in _READ_ENCODINGS:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文件编码: {path}")


def _sample_text(content: str, limit: int) -> str:
    """长文本抽样：开头50%额度 + 中段15% + 结尾20%（超长书也能抽出整体脉络）。"""
    if len(content) <= limit:
        return content
    head = content[: int(limit * 0.5)]
    mid = content[len(content) // 2 - int(limit * 0.15): len(content) // 2 + int(limit * 0.15)]
    tail = content[-int(limit * 0.2):]
    return head + "\n\n……（中略）……\n\n" + mid + "\n\n……（中略）……\n\n" + tail


_EXTRACT_PROMPTS = {
    "outline.md": (
        "你是一名专业的小说编辑。请通读以下小说片段，输出这本书的【故事大纲】："
        "主线剧情走向、核心冲突、主要角色及其目标动机。500字以内，用条目化中文输出。\n\n小说片段：\n{sample}"
    ),
    "detailed_outline.md": (
        "你是一名专业的小说编辑。请基于以下小说片段，输出这本书的【分阶段细纲】："
        "按剧情阶段（如第一卷/第一幕）划分，每个阶段列出关键事件、角色关系变化、留下的钩子。800字以内。\n\n小说片段：\n{sample}"
    ),
    "timeline.md": (
        "你是一名专业的小说编辑。请基于以下小说片段，提取这本书的【故事时间线】："
        "按先后顺序列出关键事件及其因果衔接关系，600字以内。\n\n小说片段：\n{sample}"
    ),
    "style.md": (
        "你是一名专业的小说编辑。请总结以下小说片段的【文风】，供 AI 模仿。必须涵盖："
        "叙事视角、句式长短特点、对话风格、常用修辞、情绪基调、动作/战斗描写手法、"
        "悬念与爽点的处理方式。800字以内，条目化输出。\n\n小说片段：\n{sample}"
    ),
}


def import_reference_book(book_path: str, book_name: str, llm_adapter,
                          embedding_api_key: str, embedding_url: str,
                          embedding_interface_format: str, embedding_model_name: str,
                          log_func=None) -> bool:
    """导入参考书：构建只读向量库 + LLM 抽取四件套。任一环节失败不影响其他环节。"""
    log = log_func or (lambda m: logging.info(m))
    name = _safe_book_name(book_name)
    if not name:
        log("❌ 参考书名称不能为空")
        return False
    book_dir = get_book_dir(name)
    os.makedirs(book_dir, exist_ok=True)

    try:
        content = _read_text(book_path)
    except Exception as e:
        log(f"❌ 读取参考书失败: {e}")
        return False
    if not content.strip():
        log("❌ 参考书内容为空")
        return False

    # 1) 向量库（细节检索用）
    try:
        from novel_generator.knowledge import advanced_split_content
        from novel_generator.vectorstore_utils import init_vector_store
        from embedding_adapters import create_embedding_adapter

        chunks = advanced_split_content(content)
        log(f"参考书分块完成：共 {len(chunks)} 块，开始构建向量库...")
        emb_adapter = create_embedding_adapter(
            embedding_interface_format,
            embedding_api_key,
            embedding_url if embedding_url else "http://localhost:11434/api",
            embedding_model_name,
        )
        store = init_vector_store(emb_adapter, chunks, book_dir)
        if store:
            log(f"✅ 参考书向量库构建完成（{len(chunks)} 块）")
        else:
            log("⚠️ 向量库构建失败（不影响四件套抽取，仅影响细节检索）")
    except Exception as e:
        log(f"⚠️ 向量库构建异常: {e}（继续抽取四件套）")

    # 2) 四件套抽取（LLM）
    style_sample = _sample_text(content, 8000)
    plot_sample = _sample_text(content, 20000)
    for fname, tpl in _EXTRACT_PROMPTS.items():
        out_path = os.path.join(book_dir, fname)
        try:
            sample = style_sample if fname == "style.md" else plot_sample
            log(f"正在抽取 {fname} ...")
            resp = llm_adapter.invoke(tpl.format(sample=sample))
            text = (resp or "").strip()
            if text:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
                log(f"✅ 已生成 {fname}（{len(text)} 字）")
            else:
                log(f"⚠️ {fname} 抽取结果为空，已跳过")
        except Exception as e:
            log(f"⚠️ 抽取 {fname} 失败: {e}")

    log(f"✅ 参考书《{name}》导入完成")
    return True

# =============== 生成时注入 ===============

def read_ref_md(book_name: str, fname: str, limit: int = None) -> str:
    path = os.path.join(get_book_dir(book_name), fname)
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[:limit] if limit else text
    except Exception:
        return ""


def get_reference_context(book_name: str, query: str, embedding_api_key: str,
                          embedding_url: str, embedding_interface_format: str,
                          embedding_model_name: str, k: int = 3) -> str:
    """对参考书向量库做细节检索，失败返回空串。"""
    book_dir = get_book_dir(book_name)
    if not os.path.isdir(os.path.join(book_dir, "vectorstore")):
        return ""
    try:
        from embedding_adapters import create_embedding_adapter
        from novel_generator.vectorstore_utils import get_relevant_context_from_vector_store
        emb_adapter = create_embedding_adapter(
            embedding_interface_format,
            embedding_api_key,
            embedding_url if embedding_url else "http://localhost:11434/api",
            embedding_model_name,
        )
        return get_relevant_context_from_vector_store(emb_adapter, query, book_dir, k)
    except Exception as e:
        logging.error(f"参考书向量检索失败: {e}")
        return ""


def get_generation_context_block(flow: str, query: str = None, embedding_cfg: dict = None) -> str:
    """统一注入入口：返回追加到 prompt 末尾的文本块，无内容时返回空串。

    flow:
      "architecture" -> 技能 + 参考书大纲 + 文风
      "blueprint"    -> 技能 + 大纲 + 细纲 + 时间线
      "chapter"      -> 技能 + 文风 + 向量细节检索(需 embedding_cfg)
    """
    rs = load_reference_settings()
    parts = []

    from skill_manager import get_active_skills_text
    skills_text = get_active_skills_text(rs.get("active_skills", []))
    if skills_text:
        parts.append("=== 写作技能（生成时须遵循） ===\n" + skills_text)

    book = rs.get("active_book", "")
    if book and is_book_imported(book):
        if flow in ("chapter", "architecture"):
            style = read_ref_md(book, "style.md", limit=1200)
            if style:
                parts.append(f"=== 参考书《{book}》文风（供模仿笔感，禁止照抄原文） ===\n{style}")
        if flow in ("blueprint", "architecture"):
            outline = read_ref_md(book, "outline.md", limit=1000)
            if outline:
                parts.append(f"=== 参考书《{book}》故事大纲（仅借鉴结构与冲突设计） ===\n{outline}")
        if flow == "blueprint":
            detailed = read_ref_md(book, "detailed_outline.md", limit=1200)
            if detailed:
                parts.append(f"=== 参考书《{book}》分阶段细纲 ===\n{detailed}")
            timeline = read_ref_md(book, "timeline.md", limit=800)
            if timeline:
                parts.append(f"=== 参考书《{book}》时间线 ===\n{timeline}")
        if flow == "chapter" and query and embedding_cfg:
            try:
                ctx = get_reference_context(book, query, k=3, **embedding_cfg)
                if ctx:
                    parts.append(f"=== 参考书《{book}》相关片段（借鉴写法与专有名词，禁止照抄） ===\n{ctx}")
            except Exception as e:
                logging.error(f"参考书细节检索失败: {e}")

    if not parts:
        return ""
    return "\n\n".join(parts)
