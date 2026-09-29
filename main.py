# main.py
# -*- coding: utf-8 -*-
import os
import sys

# 将工作目录固定为项目根目录，确保 config.json / app.log 等相对路径
# 无论从哪里启动（双击、命令行、快捷方式）都指向项目目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def _try_lock():
    """单实例锁：绑定固定端口。绑定失败说明已有实例在运行，
    防止多开时各实例的内存配置互相覆盖 config.json（表现为删除的配置'复活'）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 52187))
        return s
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return None


import customtkinter as ctk
import tkinter.messagebox as messagebox
from ui import NovelGeneratorGUI


def main():
    lock = _try_lock()
    if lock is None:
        root = ctk.CTk()
        root.withdraw()
        messagebox.showwarning(
            "已在运行",
            "AI_NovelGenerator 已经在运行中，请勿重复打开。\n\n"
            "多开会导致配置互相覆盖（删除的配置会\"复活\"、参数丢失）。"
        )
        root.destroy()
        return

    app = ctk.CTk()
    gui = NovelGeneratorGUI(app)
    app.mainloop()

    try:
        lock.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
