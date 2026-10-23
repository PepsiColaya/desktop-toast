# -*- coding: utf-8 -*-
"""可行性探测：通知中心里能拿到哪些应用身份信息，能否对应到正在运行的程序。

只读，不修改任何东西。用来判断「按软件选择性监听」是否可行。
"""
import asyncio
import ctypes
import ctypes.wintypes as wt
import os

from winrt.windows.ui.notifications import NotificationKinds
from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_name(pid: int) -> str:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return "?"
    finally:
        k32.CloseHandle(h)


def enum_windows() -> list[tuple[str, str, int]]:
    """返回 [(进程名, 窗口标题, pid)]，只取可见且有标题的顶层窗口。"""
    user32 = ctypes.windll.user32
    out: list[tuple[str, str, int]] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append((process_name(pid.value), buf.value, pid.value))
        return True

    user32.EnumWindows(proc(cb), 0)
    return out


async def dump_notifications():
    listener = UserNotificationListener.current
    status = listener.get_access_status()
    print("access status:", status)
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        status = await listener.request_access_async()
        print("after request:", status)
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        print("!! 无权限，无法继续")
        return

    notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    print(f"\n通知中心当前共 {len(notifs)} 条 toast\n")
    print("=" * 78)

    groups: dict[tuple[str, str], list] = {}
    for n in notifs:
        ai = n.app_info
        aumid = ai.app_user_model_id or "(空)"
        info = ai.display_info
        name = (info.display_name if info else "") or "(无名)"
        texts: list[str] = []
        try:
            binding = n.notification.visual.get_binding("ToastGeneric")
            if binding is not None:
                texts = [t.text for t in binding.get_text_elements() if t.text]
        except Exception:
            pass
        groups.setdefault((aumid, name), []).append((n.id, texts))

    for (aumid, name), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n应用名 : {name}")
        print(f"AUMID  : {aumid}")
        print(f"通知数 : {len(items)}")
        for nid, texts in items[:2]:
            joined = " / ".join(texts).replace("\n", " ")
            print(f"   #{nid}  {joined[:70]}")

    print("\n" + "=" * 78)
    print(f"共 {len(groups)} 个不同应用发过通知")
    return groups


def main():
    groups = asyncio.run(dump_notifications())

    print("\n\n当前运行且带窗口的进程：")
    print("=" * 78)
    wins = enum_windows()
    seen = set()
    for pname, title, pid in wins:
        key = pname.lower()
        if key in seen:
            continue
        seen.add(key)
        print(f"  {pname:28s} pid={pid:<7d} {title[:40]}")

    print(f"\n共 {len(seen)} 个进程有可见窗口")

    if groups:
        aumids = {a.split("!")[0].lower() for a, _ in groups}
        print("\n通知来源 AUMID 前缀 vs 进程名，粗匹配：")
        for pname, _, _ in wins:
            stem = pname.lower().removesuffix(".exe")
            hit = [a for a in aumids if stem in a]
            if hit:
                print(f"  {pname:28s} -> {hit}")


if __name__ == "__main__":
    main()
