# ui/reference_tab.py
# -*- coding: utf-8 -*-
"""参考书/技能管理页（最小 UI）：
- 参考书：下拉选择激活书 + 导入(txt) + 删除
- 技能：复选框启用/禁用，勾选即持久化到 config.json
"""
import os
import threading
import logging
import customtkinter as ctk
from tkinter import filedialog, messagebox

from llm_adapters import create_llm_adapter
from skill_manager import list_skills
from reference_manager import (
    list_reference_books,
    import_reference_book,
    delete_reference_book,
    load_reference_settings,
    save_reference_settings,
)


def build_reference_tab(self):
    self.reference_tab = self.tabview.add("参考书/技能")
    self.reference_tab.columnconfigure(0, weight=1)
    self.reference_tab.rowconfigure(1, weight=1)

    # ---------- 参考书区 ----------
    book_frame = ctk.CTkFrame(self.reference_tab)
    book_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    book_frame.columnconfigure(1, weight=1)

    ctk.CTkLabel(book_frame, text="激活参考书:", font=("Microsoft YaHei", 12)).grid(row=0, column=0, padx=8, pady=8, sticky="w")

    rs = load_reference_settings()
    self.ref_book_var = ctk.StringVar(value=rs.get("active_book", ""))
    self.ref_book_menu = ctk.CTkOptionMenu(
        book_frame, variable=self.ref_book_var,
        values=["(不使用)"] + list_reference_books(),
        command=lambda _v: _on_book_changed(self),
        font=("Microsoft YaHei", 12),
    )
    self.ref_book_menu.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

    ctk.CTkButton(book_frame, text="导入参考书", width=90, font=("Microsoft YaHei", 12),
                  command=lambda: _import_reference_book(self)).grid(row=0, column=2, padx=4, pady=8)
    ctk.CTkButton(book_frame, text="删除", width=60, font=("Microsoft YaHei", 12),
                  fg_color="red", command=lambda: _delete_reference_book(self)).grid(row=0, column=3, padx=(4, 8), pady=8)

    ctk.CTkLabel(
        book_frame, justify="left", font=("Microsoft YaHei", 11),
        text="导入后自动抽取大纲/细纲/时间线/文风（四件套）+ 构建细节检索向量库；\n"
             "激活后：架构/蓝图生成注入大纲，章节草稿注入文风+细节片段。参考书来源请确保你有权使用。"
    ).grid(row=1, column=0, columnspan=4, padx=8, pady=(0, 8), sticky="w")

    # ---------- 技能区 ----------
    skill_frame = ctk.CTkScrollableFrame(self.reference_tab, orientation="vertical")
    skill_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
    ctk.CTkLabel(skill_frame, text="启用技能（勾选即保存；往项目 skills/ 目录放 .md 即可新增技能）:",
                 font=("Microsoft YaHei", 12)).pack(anchor="w", padx=6, pady=6)

    self.ref_skill_vars = {}
    active_skills = set(rs.get("active_skills", []))
    for name in list_skills():
        var = ctk.BooleanVar(value=name in active_skills)
        self.ref_skill_vars[name] = var
        ctk.CTkCheckBox(
            skill_frame, text=name, variable=var, font=("Microsoft YaHei", 12),
            command=lambda n=name: _on_skill_toggled(self, n),
        ).pack(anchor="w", padx=12, pady=3)


def _on_book_changed(self):
    book = self.ref_book_var.get()
    active = "(不使用)" if book == "(不使用)" else book
    save_reference_settings(active_book=active)
    self.safe_log(f"参考书已切换为: {active}")


def _on_skill_toggled(self, name):
    enabled = [n for n, v in self.ref_skill_vars.items() if v.get()]
    save_reference_settings(active_skills=enabled)
    self.safe_log(f"技能已更新: {enabled if enabled else '(无)'}")


def _import_reference_book(self):
    selected = filedialog.askopenfilename(
        title="选择参考书文本文件",
        filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
    )
    if not selected:
        return
    default_name = os.path.splitext(os.path.basename(selected))[0]
    dialog = ctk.CTkInputDialog(
        text=f"请输入参考书名称（默认: {default_name}）:",
        title="参考书名称",
    )
    book_name = (dialog.get_input() or "").strip() or default_name

    def task():
        try:
            self.safe_log(f"开始导入参考书《{book_name}》，导入期间请勿关闭程序...")
            llm_adapter = create_llm_adapter(
                interface_format=self.interface_format_var.get(),
                base_url=self.base_url_var.get(),
                model_name=self.model_name_var.get(),
                api_key=self.api_key_var.get(),
                temperature=self.temperature_var.get(),
                max_tokens=self.max_tokens_var.get(),
                timeout=self.timeout_var.get(),
            )
            ok = import_reference_book(
                book_path=selected,
                book_name=book_name,
                llm_adapter=llm_adapter,
                embedding_api_key=self.embedding_api_key_var.get().strip(),
                embedding_url=self.embedding_url_var.get().strip(),
                embedding_interface_format=self.embedding_interface_format_var.get().strip(),
                embedding_model_name=self.embedding_model_name_var.get().strip(),
                log_func=self.safe_log,
            )
            if ok:
                self.safe_log(f"✅ 参考书《{book_name}》导入完成，可在上方下拉选择激活。")
                self.ref_book_menu.configure(values=["(不使用)"] + list_reference_books())
        except Exception as e:
            logging.error(f"导入参考书异常: {e}")
            self.safe_log(f"❌ 导入参考书失败: {e}")

    threading.Thread(target=task, daemon=True).start()


def _delete_reference_book(self):
    book = self.ref_book_var.get()
    if not book or book == "(不使用)":
        messagebox.showwarning("提示", "请先在下拉框中选择要删除的参考书")
        return
    if not messagebox.askyesno("确认删除", f"确定删除参考书《{book}》吗？\n其向量库与四件套文件将被移除。"):
        return
    if delete_reference_book(book):
        save_reference_settings(active_book="(不使用)")
        self.ref_book_var.set("(不使用)")
        self.ref_book_menu.configure(values=["(不使用)"] + list_reference_books())
        self.safe_log(f"已删除参考书《{book}》")
    else:
        messagebox.showerror("错误", "删除失败（可能目录被占用），请关闭占用程序后重试")
