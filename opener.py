# -*- coding: utf-8 -*-
"""点击卡片时唤起来源应用。

三种情况分开处理，因为「打开」的含义不一样：

* **手机连接转发的通知** —— 真实来源在手机上，电脑端打不开那个 App，
  能做的是把「手机连接」窗口调出来，用户接着在里面看。
* **PC 微信** —— 有自己的窗口，走窗口级唤醒（wechat.open_wechat），
  比系统激活更稳，能复用已经开着的那个窗口。
* **其它应用** —— 先用系统的 IApplicationActivationManager 按 AUMID 激活
  （打包应用、商店应用都支持，没在运行就直接启动）；
  激活不了再退回「按窗口标题找」，常见于没注册 AUMID 的 Win32 程序。

全部是尽力而为：认不出来就返回 False，不弹任何错误框。
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_void_p, c_ulong, c_wchar_p

import apps
import wechat

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32

# 手机连接的 AUMID 固定是这个形态，注册表里可能是 Setup/Notifications 变体
PHONE_LINK_AUMID = "Microsoft.YourPhone_8wekyb3d8bbwe!App"

SW_RESTORE = 9


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    """把 ``{45BA127D-10A8-46EA-8AB7-56EA9078943C}`` 解析成 GUID 结构。"""
    g = _GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


CLSID_APPLICATION_ACTIVATION_MANAGER = _guid("{45BA127D-10A8-46EA-8AB7-56EA9078943C}")
IID_IAPPLICATION_ACTIVATION_MANAGER = _guid("{2E941141-7F97-4756-BA1D-9DECDE894A3D}")


def _activate_by_aumid(aumid: str) -> bool:
    """用 IApplicationActivationManager::ActivateApplication 启动/聚焦应用。

    这是系统提供的正规入口，失败只返回错误码，不会弹「找不到应用」之类的对话框。
    """
    if not aumid:
        return False

    ole32.CoInitialize(None)
    ptr = c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            byref(CLSID_APPLICATION_ACTIVATION_MANAGER),
            None,
            1,                      # CLSCTX_LOCAL_SERVER
            byref(IID_IAPPLICATION_ACTIVATION_MANAGER),
            byref(ptr),
        )
        if hr != 0 or not ptr:
            return False

        # vtable: 0 QueryInterface / 1 AddRef / 2 Release / 3 ActivateApplication
        vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
        activate = ctypes.WINFUNCTYPE(
            ctypes.c_long, c_void_p, c_wchar_p, c_wchar_p, ctypes.c_uint, POINTER(c_ulong),
        )(vtable[3])

        pid = c_ulong()
        hr = activate(ptr, aumid, None, 0, byref(pid))
        return hr >= 0
    except Exception:
        return False
    finally:
        if ptr:
            try:
                vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
                ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtable[2])(ptr)   # Release
            except Exception:
                pass
        ole32.CoUninitialize()


def _window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value.strip()


def _focus_window_by_title(name: str) -> bool:
    """按窗口标题找应用并拉到前台。

    只用于前面几种方式都失败时的兜底：标题包含应用名就算命中，
    优先可见窗口，其次隐藏窗口（托盘里的那种也能救出来）。
    """
    name = (name or "").strip()
    if len(name) < 2:
        return False

    low = name.lower()
    exact: list[int] = []
    partial: list[int] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, c_void_p, c_void_p)

    def cb(hwnd, _lparam):
        title = _window_title(hwnd)
        if not title:
            return True
        t = title.lower()
        if t == low or t.startswith(low):
            exact.append(hwnd)
        elif low in t:
            partial.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)

    for hwnd in exact + partial:
        if not user32.IsWindowVisible(hwnd):
            continue
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True

    # 没有可见的，试试托盘里藏着的
    for hwnd in exact + partial:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    return False


def open_source(aumid: str = "", app_name: str = "") -> bool:
    """按来源应用唤起到前台，返回是否成功。"""
    aumid = (aumid or "").strip()
    app_name = (app_name or "").strip()

    # 1. 手机连接转发：真实来源在手机上，只能把手机连接调出来
    if apps.is_phone_link_aumid(aumid):
        return _activate_by_aumid(PHONE_LINK_AUMID) or _focus_window_by_title("手机连接")

    # 2. PC 微信：窗口级唤醒更稳
    if apps.is_pc_wechat(aumid) or (not aumid and "微信" in app_name):
        if wechat.open_wechat():
            return True

    # 3. 其它应用：先系统激活，再按窗口标题兜底
    if _activate_by_aumid(aumid):
        return True
    if app_name and _focus_window_by_title(app_name):
        return True
    return False
