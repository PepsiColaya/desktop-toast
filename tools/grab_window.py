# -*- coding: utf-8 -*-
"""把微信的某个窗口（含隐藏窗口）抓成 PNG，用来判断它到底是什么。

用法：
    .venv\\Scripts\\python.exe tools\\grab_window.py            # 抓所有微信窗口
    .venv\\Scripts\\python.exe tools\\grab_window.py 0x104F8    # 抓指定句柄
    .venv\\Scripts\\python.exe tools\\grab_window.py 0x104F8 --show  # 先显示再抓

产物落在 tools/captures/ 下。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WECHAT_EXES = ("weixin.exe", "wechat.exe")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")

SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def exe_of(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        return buf.value if kernel32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel32.CloseHandle(h)


def text_of(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def wechat_windows() -> list[dict]:
    rows: list[dict] = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not exe_of(pid.value).lower().endswith(WECHAT_EXES):
            return True
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        rows.append({"hwnd": hwnd, "cls": class_of(hwnd),
                     "title": text_of(hwnd),
                     "visible": bool(user32.IsWindowVisible(hwnd)),
                     "w": r.r - r.l, "h": r.b - r.t})
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return rows


def capture(hwnd: int, path: str) -> bool:
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    w, h = r.r - r.l, r.b - r.t
    if w <= 0 or h <= 0:
        return False

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not ok:
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, r.l, r.t, SRCCOPY)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h          # 负数 = 自上而下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf,
                              ctypes.byref(bmi), DIB_RGB_COLORS)
        if not got:
            return False

        from PySide6.QtGui import QGuiApplication, QImage
        app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        img = QImage(buf.raw, w, h, w * 4, QImage.Format_ARGB32)
        ok2 = img.save(path, "PNG")
        del app
        return bool(ok2)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


def main() -> int:
    set_dpi_aware()
    os.makedirs(OUT_DIR, exist_ok=True)

    targets: list[dict] = []
    if len(sys.argv) > 1 and sys.argv[1].startswith("0x"):
        hwnd = int(sys.argv[1], 16)
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        targets = [{"hwnd": hwnd, "cls": class_of(hwnd), "title": text_of(hwnd),
                    "visible": bool(user32.IsWindowVisible(hwnd)),
                    "w": r.r - r.l, "h": r.b - r.t}]
    else:
        targets = [w for w in wechat_windows() if w["w"] > 0 and w["h"] > 0]

    if "--show" in sys.argv:
        for t in targets:
            user32.ShowWindow(t["hwnd"], 8)  # SW_SHOWNA
        time.sleep(0.6)

    if not targets:
        print("没有可抓的窗口")
        return 1

    for t in targets:
        name = f"w_{t['hwnd']:X}_{t['w']}x{t['h']}.png"
        path = os.path.join(OUT_DIR, name)
        ok = capture(t["hwnd"], path)
        mark = "OK " if ok else "FAIL"
        print(f"  [{mark}] {t['w']}x{t['h']:<5} hwnd=0x{t['hwnd']:X} "
              f"class={t['cls'][:32]:<32} title={t['title'][:14]!r} -> {name}")

    print(f"\n输出目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
