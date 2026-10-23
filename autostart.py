# -*- coding: utf-8 -*-
"""开机自启：写当前用户的 Run 注册表项，不需要管理员权限。"""
from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DesktopToast"

# 改名前的自启项名。老用户升级后这一项会残留，不清掉会开机启动两个程序
LEGACY_VALUE_NAMES = ("WeChatToast",)


def _command() -> str:
    """自启命令。

    打包后直接指向 exe；源码运行则用 pythonw.exe 启动 main.py，
    避免每次开机弹一个黑色控制台窗口。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    import config as cfgmod

    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    script = os.path.join(cfgmod.app_dir(), "main.py")
    return f'"{exe}" "{script}"'


def _present_names() -> list[str]:
    """注册表里实际存在且非空的自启项名（含改名前的旧名字）。"""
    try:
        import winreg

        found: list[str] = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            for name in (VALUE_NAME, *LEGACY_VALUE_NAMES):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if value:
                    found.append(name)
        return found
    except Exception:
        return []


def is_enabled() -> bool:
    return bool(_present_names())


def has_legacy() -> bool:
    """注册表里还留着改名前的自启项。"""
    return any(n in _present_names() for n in LEGACY_VALUE_NAMES)


def migrate_legacy() -> bool:
    """把旧名字的自启项重写成新名字，命令指向当前程序。

    不搬的话，新版启动时看到「自启已开」就不会重写，结果开机起来的还是旧 exe。
    """
    if not has_legacy():
        return False
    return set_enabled(True)


def set_enabled(enabled: bool) -> bool:
    """开/关开机自启，返回是否操作成功。

    打开时顺手删掉改名前的旧自启项；关闭时新旧都删，避免残留。
    """
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            for name in LEGACY_VALUE_NAMES:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            if not enabled:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        from logger import get

        get("autostart").warning("设置开机自启失败: %s", e)
        return False
