# -*- coding: utf-8 -*-
"""开机自启：写当前用户的 Run 注册表项，不需要管理员权限。"""
from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WeChatToast"


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


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def set_enabled(enabled: bool) -> bool:
    """开/关开机自启，返回是否操作成功。"""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        from logger import get

        get("autostart").warning("设置开机自启失败: %s", e)
        return False
