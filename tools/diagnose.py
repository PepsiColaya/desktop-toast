# -*- coding: utf-8 -*-
"""诊断「为什么收不到微信消息」。

微信 4.x 有三条可能的入口，本脚本逐条验证，不猜：
  1. Windows 通知中心（Toast）        → UserNotificationListener
  2. UI Automation（无障碍树）        → 读控件
  3. 微信自己画的弹窗                  → 盯窗口 + 截图 OCR

用法：
    .venv\\Scripts\\python.exe tools\\diagnose.py
    .venv\\Scripts\\python.exe tools\\diagnose.py --watch 60
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfgmod  # noqa: E402
from watcher import WeChatWatcher, _extract_texts, app_identity  # noqa: E402

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WECHAT_EXES = ("weixin.exe", "wechat.exe")
CAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")

SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002


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


def section(title: str) -> None:
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------------------------------------------------------------- 窗口枚举

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
        rows.append({
            "hwnd": hwnd, "pid": pid.value,
            "cls": class_of(hwnd), "title": text_of(hwnd),
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "w": r.r - r.l, "h": r.b - r.t,
        })
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return rows


# ---------------------------------------------------------------- 截图 / OCR

def capture_bmp(hwnd: int, path: str) -> bool:
    """把窗口抓成 BMP（不依赖 Qt）。"""
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    w, h = r.r - r.l, r.b - r.t
    if w <= 0 or h <= 0 or w > 4000 or h > 3000:
        return False

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        if not user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT):
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, r.l, r.t, SRCCOPY)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = h          # 正数 = 自下而上，符合 BMP 规范
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf,
                               ctypes.byref(bmi), 0):
            return False

        # GDI 给的是全 0 的 alpha 通道，WIC 解码时会当成全透明，必须补成不透明
        pix = bytearray(buf.raw)
        pix[3::4] = b"\xff" * (w * h)

        header = b"BM" + struct.pack("<IHHI", 14 + 40 + len(pix), 0, 0, 54)
        info = (struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0,
                            len(pix), 2835, 2835, 0, 0))
        with open(path, "wb") as f:
            f.write(header)
            f.write(info)
            f.write(bytes(pix))
        return True
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


def _compact(text: str) -> str:
    text = re.sub(r"(?<=[\u4e00-\u9fff\uff00-\uffef])\s+"
                  r"(?=[\u4e00-\u9fff\uff00-\uffef])", "", text)
    return text.strip()


async def ocr_file(path: str, scale: int = 2) -> list[str]:
    """识别图片里的文字。

    小字号直接识别错字很多，先用 Pillow 做一次 LANCZOS 放大再交给 OCR。
    """
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import (
            DataWriter, InMemoryRandomAccessStream,
        )
    except Exception:
        return []

    engine = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return []

    target = path
    if scale > 1:
        try:
            from PIL import Image

            with Image.open(path) as im:
                im = im.convert("RGB")
                big = im.resize((im.width * scale, im.height * scale),
                                Image.LANCZOS)
                target = os.path.splitext(path)[0] + f"_x{scale}.png"
                big.save(target, "PNG")
        except Exception:
            target = path

    with open(target, "rb") as f:
        raw = f.read()
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(raw)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    out = []
    for line in result.lines:
        t = _compact(line.text)
        if t:
            out.append(t)
    return out


# ---------------------------------------------------------------- 第 1 节

def check_os() -> None:
    section("1. 系统与通知权限")
    ver = sys.getwindowsversion()
    print(f"  Windows: {ver.major}.{ver.minor} build {ver.build}")
    print("  " + ("✓ 满足 1809+ 要求" if ver.build >= 17763
                  else "✗ 低于 1809，通知监听 API 不可用"))
    try:
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener, UserNotificationListenerAccessStatus,
        )

        status = UserNotificationListener.current.get_access_status()
        names = {
            UserNotificationListenerAccessStatus.ALLOWED: "已允许",
            UserNotificationListenerAccessStatus.DENIED: "被拒绝",
            UserNotificationListenerAccessStatus.UNSPECIFIED: "未设置",
        }
        print(f"  通知访问权限: {names.get(status, status)}")
    except Exception as e:
        print(f"  ✗ 读取权限失败: {e}")


# ---------------------------------------------------------------- 第 2 节

async def dump_current() -> None:
    section("2. 通知中心当前内容")
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import UserNotificationListener

    notifs = await UserNotificationListener.current.get_notifications_async(
        NotificationKinds.TOAST)
    print(f"  共 {len(notifs)} 条 Toast")
    for n in notifs:
        aumid, name = app_identity(n)
        print(f"    {name or '?'}  [{aumid[:40]}]")
        print(f"      {_extract_texts(n)}")


# ---------------------------------------------------------------- 第 3 节

def check_wechat() -> None:
    section("3. 微信进程与窗口")
    wins = wechat_windows()
    if not wins:
        print("  ✗ 没有检测到微信进程（weixin.exe / wechat.exe）")
        return
    pids = sorted({w["pid"] for w in wins})
    print(f"  进程数 {len(pids)}   pid={pids}")
    for w in sorted(wins, key=lambda x: -(x["w"] * x["h"])):
        if w["w"] <= 0 or w["h"] <= 0:
            continue
        print(f"    [{'可见' if w['visible'] else '隐藏'}] {w['w']}x{w['h']:<5} "
              f"class={w['cls'][:34]:<34} title={w['title'][:12]!r}")


# ---------------------------------------------------------------- 第 4 节

def check_wpn_database() -> bool:
    """返回 True 表示微信历史上推过系统通知。"""
    section("4. 历史证据：微信有没有往通知中心推过消息")
    src = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                       r"Microsoft\Windows\Notifications\wpndatabase.db")
    if not os.path.exists(src):
        print("  找不到通知数据库，跳过")
        return False

    tmp = os.path.join(tempfile.gettempdir(), "wpn_diag.db")
    try:
        shutil.copy2(src, tmp)
        for ext in ("-wal", "-shm"):
            if os.path.exists(src + ext):
                shutil.copy2(src + ext, tmp + ext)
        con = sqlite3.connect(tmp)
        con.row_factory = sqlite3.Row
        rows = list(con.execute("""
            SELECT h.PrimaryId AS aumid, COUNT(n.Id) AS cnt
            FROM NotificationHandler h
            LEFT JOIN Notification n ON n.HandlerId = h.RecordId
            GROUP BY h.RecordId ORDER BY cnt DESC
        """))
        total = len(rows)
        con.close()
    except Exception as e:
        print(f"  读取失败: {e}")
        return False

    hits = [r for r in rows
            if any(k in (r["aumid"] or "").lower()
                   for k in ("wechat", "weixin", "tencent"))]
    print(f"  通知中心共登记 {total} 个应用处理器")
    print(f"  其中微信相关: {len(hits)} 个")
    if hits:
        for r in hits:
            print(f"    {r['aumid']}  {r['cnt']} 条")
        return any(r["cnt"] for r in hits)

    print()
    print("  ✗ 微信从未在这台机器上注册过通知处理器。")
    print("    结论：不是本程序漏掉了，是微信根本没往通知中心推。")
    return False


# ---------------------------------------------------------------- 第 5 节

def check_uia() -> bool:
    """返回 True 表示能从无障碍树读到微信界面。"""
    section("5. UI Automation：能不能读到微信界面")
    try:
        import uiautomation as auto
    except Exception as e:
        print(f"  ✗ 未安装 uiautomation（{e}）")
        return False

    cand = [w for w in wechat_windows()
            if w["visible"] and w["w"] > 400 and w["h"] > 300]
    if not cand:
        print("  ! 微信没有可见的主窗口（最小化到托盘了），本节跳过")
        print("    想看这一节，请先把微信主界面打开再跑一次")
        return False

    main = max(cand, key=lambda w: w["w"] * w["h"])
    auto.SetGlobalSearchTimeout(1.0)
    root = auto.ControlFromHandle(main["hwnd"])
    if root is None:
        print("  ✗ 无法从窗口句柄拿到 UIA 根节点")
        return False

    nodes: list[tuple[int, object]] = []
    queue = [(root, 0)]
    while queue and len(nodes) < 4000:
        ctrl, depth = queue.pop(0)
        if depth >= 12:
            continue
        try:
            children = ctrl.GetChildren()
        except Exception:
            continue
        for ch in children:
            nodes.append((depth + 1, ch))
            queue.append((ch, depth + 1))

    print(f"  主窗口: class={main['cls']} title={main['title']!r}")
    print(f"  UIA 子树控件数: {len(nodes)}")
    if not nodes:
        print()
        print("  ✗ 微信主窗口对 UIA 完全封闭（只有根节点，没有任何子控件）。")
        print("    说明它的 Qt 是无障碍功能被裁掉的版本，读控件这条路走不通。")
        return False

    items = []
    for depth, c in nodes:
        try:
            if (getattr(c, "AutomationId", "") or "").startswith("session_item_"):
                items.append(c)
        except Exception:
            continue
    print(f"  其中会话项(session_item_*): {len(items)}")
    for c in items[:8]:
        print(f"    name={c.Name[:70]!r}")
    return bool(items)


# ---------------------------------------------------------------- 第 6 节

async def watch(seconds: int) -> None:
    section(f"6. 实时监听 {seconds} 秒")
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import UserNotificationListener

    os.makedirs(CAP_DIR, exist_ok=True)
    cfg = cfgmod.load()
    checker = WeChatWatcher(on_message=lambda m: None,
                            enabled_apps=cfg.get("enabled_apps", []))

    listener = UserNotificationListener.current
    try:
        seen = {n.id for n in await listener.get_notifications_async(
            NotificationKinds.TOAST)}
    except Exception:
        seen = set()
    print(f"  忽略现有 {len(seen)} 条历史通知")

    base = {w["hwnd"]: w["visible"] for w in wechat_windows()}
    print(f"  记录微信现有 {len(base)} 个窗口作为基线")
    print()
    print("  现在去收一条微信消息（建议先把微信最小化到托盘），有新动静会立刻打印。")
    print()

    got_toast = False
    got_popup = False
    deadline = time.time() + seconds

    while time.time() < deadline:
        # 1) 系统通知
        try:
            notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
            for n in notifs:
                if n.id in seen:
                    continue
                seen.add(n.id)
                got_toast = True
                texts = _extract_texts(n)
                aumid, name = app_identity(n)
                ok = checker.app_enabled(aumid, name, texts)
                print(f"  [{time.strftime('%H:%M:%S')}] ① 新系统通知")
                print(f"      aumid={aumid!r} name={name!r}")
                print(f"      文本={texts}")
                print(f"      本程序会提醒: {'是' if ok else '否'}")
        except Exception as e:
            print(f"  读取通知失败: {e}")

        # 2) 微信自己的窗口变化
        for w in wechat_windows():
            if w["w"] <= 0 or w["h"] <= 0:
                continue
            was = base.get(w["hwnd"])
            became_visible = (was is False and w["visible"])
            is_new = (was is None)
            if not (became_visible or is_new):
                if was != w["visible"]:
                    base[w["hwnd"]] = w["visible"]
                continue

            base[w["hwnd"]] = w["visible"]
            if not w["visible"]:
                continue
            # 主窗口不算弹窗
            if w["w"] > 700 and w["h"] > 500:
                continue

            got_popup = True
            stamp = time.strftime("%H%M%S")
            raw = os.path.join(CAP_DIR, f"popup_{stamp}_0x{w['hwnd']:X}.bmp")
            print(f"  [{time.strftime('%H:%M:%S')}] ② 微信弹出了自己的窗口 "
                  f"{w['w']}x{w['h']} class={w['cls']} title={w['title']!r}")
            if capture_bmp(w["hwnd"], raw):
                lines = await ocr_file(raw, 2)
                if lines:
                    print("      OCR 结果:")
                    for ln in lines:
                        print(f"        {ln}")
                else:
                    print("      OCR 无结果（窗口可能还没画完）")
                print(f"      截图: {raw}")
        await asyncio.sleep(0.2)

    print()
    print("  ---------- 本轮结果 ----------")
    if not got_toast:
        print("  ① 系统通知：一条都没有 → 通知中心这条路对本微信无效")
    if got_popup:
        print("  ② 微信自绘弹窗：捕获到了 → 可以靠「盯窗口 + 截图 OCR」实现提醒")
    if not got_popup:
        print("  ② 微信自绘弹窗：没捕获到")
        print("     可能消息来时微信主窗口是开着的（微信只在后台时才弹）")
        print("     也可能微信的「新消息通知」被关掉了")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="实时监听 N 秒")
    args = ap.parse_args()

    set_dpi_aware()
    check_os()
    await dump_current()
    check_wechat()
    toast_ok = check_wpn_database()
    uia_ok = check_uia()

    section("小结")
    print(f"  ① 系统通知中心  : {'可用' if toast_ok else '不可用'}")
    print(f"  ② UI Automation : {'可用' if uia_ok else '不可用'}")
    print("  ③ 自绘弹窗 OCR  : 需要 --watch 实测")

    if args.watch:
        await watch(args.watch)
    else:
        print()
        print("  想确认第 ③ 条，跑：")
        print("    .venv\\Scripts\\python.exe tools\\diagnose.py --watch 60")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
