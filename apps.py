# -*- coding: utf-8 -*-
"""枚举当前正在运行、且有可见窗口的应用。

设置面板用它生成「可监听应用」的复选列表：用户勾哪些，就只提醒哪些。
只列有可见窗口的进程，避免把一堆后台服务刷进列表。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
version = ctypes.windll.version

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 系统壳、输入法、以及程序自己，没必要出现在列表里
SKIP_EXES = {
    "explorer.exe",
    "textinputhost.exe",
    "applicationframehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "sihost.exe",
    "ctfmon.exe",
    "dwm.exe",
    "conhost.exe",
    "wechattoast.exe",
    "runtimebroker.exe",
    "widgets.exe",
    "lockapp.exe",
    "microsoftedgecp.exe",       # Edge 的内容进程，不是独立应用
}

# 名字里带这些的通常是系统壳的辅助进程
SKIP_CONTAINS = ("composableshell",)

# 跑在解释器里的程序（源码运行时的自己、各种脚本工具）
SKIP_PREFIXES = ("python", "pythonw")


def _window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value.strip()


def _process_exe(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        kernel32.CloseHandle(h)


def _file_description(path: str) -> str:
    """读 exe 的版本信息，拿到「Google Chrome」这种给人看的名字。"""
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return ""

        ptr = ctypes.c_void_p()
        ln = ctypes.c_uint()
        if not version.VerQueryValueW(
            buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)
        ):
            return ""
        if not ln.value:
            return ""
        lang, codepage = ctypes.cast(
            ptr, ctypes.POINTER(ctypes.c_ushort * 2)
        ).contents
        sub = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
        if not version.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(ln)):
            return ""
        # ln 是按字节计的长度，wstring_at 会把结尾的 \0 也读进来，这里去掉
        text = ctypes.wstring_at(ptr, ln.value).replace("\x00", "").strip()
        return text
    except Exception:
        return ""


_ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def list_running_apps(limit: int = 40) -> list[dict]:
    """返回正在运行的应用列表。

    每项：{exe, name, path, title, pid}，按名称排序，同 exe 只保留一次。
    """
    found: dict[str, dict] = {}

    def cb(hwnd, _lparam):
        if len(found) >= limit:
            return False
        if not user32.IsWindowVisible(hwnd):
            return True
        if not _window_title(hwnd):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True

        path = _process_exe(pid.value)
        if not path:
            return True

        base = os.path.basename(path).lower()
        if base in SKIP_EXES or base.startswith(SKIP_PREFIXES):
            return True
        if any(s in base for s in SKIP_CONTAINS):
            return True
        if base in found:
            return True

        stem = os.path.splitext(base)[0]
        name = _file_description(path).replace("\x00", "").strip()
        found[base] = {
            "exe": base,
            "name": name or stem.replace("_", " ").title(),
            "path": path,
            "title": _window_title(hwnd),
            "pid": pid.value,
        }
        return True

    try:
        user32.EnumWindows(_ENUMPROC(cb), 0)
    except Exception:
        pass

    apps = list(found.values())
    apps.sort(key=lambda a: (a["name"].lower(), a["exe"]))
    return apps


def match_patterns(app: dict) -> list[str]:
    """把应用转成一组小写匹配串。

    通知里能拿到的是 AUMID（如 WorkBuddy.WorkBuddyAI）和显示名（WorkBuddy AI），
    两者都可能和 exe 名不一致，所以把能拿到的都放进去做子串匹配。
    """
    pats: list[str] = []

    def add(s: str) -> None:
        s = (s or "").strip().lower()
        if s and s not in pats:
            pats.append(s)

    add(app.get("name", ""))
    exe = app.get("exe", "")
    if exe:
        add(exe)
        add(os.path.splitext(exe)[0])
    return pats


if __name__ == "__main__":
    for a in list_running_apps():
        print(f"{a['name']:<28} {a['exe']:<26} {a['title'][:40]}")
