# -*- coding: utf-8 -*-
"""唤起微信主窗口（微信 4.x 自绘，只能把主窗口拉到前台）。"""
from __future__ import annotations

import ctypes
import os

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9


def _process_exe(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(1024)
    size = ctypes.c_ulong(1024)
    ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    kernel32.CloseHandle(h)
    return buf.value.lower() if ok else ""


def _window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value.strip()


def find_wechat_window() -> int:
    """返回微信主窗口句柄；找不到返回 0。

    微信 4.x 会创建多个 Weixin.exe 顶层窗口，优先取标题为「微信」且可见的那个。
    """
    candidates: list[tuple[int, bool, str]] = []
    result = [0]

    def cb(hwnd, _lparam):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not _process_exe(pid.value).endswith("weixin.exe"):
            return True
        title = _window_title(hwnd)
        if title not in ("微信", "Weixin", "WeChat"):
            return True
        candidates.append((hwnd, bool(user32.IsWindowVisible(hwnd)), title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(cb), 0)

    if not candidates:
        return 0

    # 可见的「微信」优先，其次任意可见窗口，最后兜底
    candidates.sort(key=lambda c: (c[2] == "微信", c[1]), reverse=True)
    result[0] = candidates[0][0]
    return result[0]


def _force_foreground(hwnd: int) -> None:
    """绕过 Windows 的前台窗口限制，尽量把窗口拉到最前。"""
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0

    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))

    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_tid, cur_tid, False)


def open_wechat() -> bool:
    """把微信唤到前台。成功返回 True。"""
    hwnd = find_wechat_window()
    if hwnd:
        if not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_SHOW)
        user32.ShowWindow(hwnd, SW_RESTORE)
        _force_foreground(hwnd)
        return True

    # 微信没在运行：走自定义协议启动
    try:
        os.startfile("weixin://")
        return True
    except Exception:
        return False
