# -*- coding: utf-8 -*-
"""监听 Windows 通知中心，捕获微信（以及用户勾选的其他应用）的新消息。

通过 UserNotificationListener 读取通知中心的 Toast，不注入微信进程、不读数据库。

注意：这条路只对「会把消息推送到 Windows 通知中心」的应用有效。
微信 4.x 属于不推送的那一类（实测它的通知处理器数为 0），
具体原因和可选的替代方案见 README 的「微信 4.x 收不到消息」一节。

监听哪些应用由 config 的 enabled_apps 决定，默认只有微信。
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

from winrt.windows.ui.notifications import NotificationKinds
from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)

from logger import get

# 微信在不同版本/语言下的应用名与标识里都可能出现这些词
WECHAT_TITLES = ("微信", "wechat", "weixin")

# 群消息格式为「发送者 : 内容」，冒号后面带空格。
# 这里要求冒号后必须有空白，是为了避开单聊正文里常见的中文冒号：
# 「会议时间：明天下午三点」不该被拆成 发送者=会议时间。
SENDER_SPLIT = re.compile(r"^(.{1,20}?)\s*[:：]\s+(.+)$", re.S)

# 发送者名里出现这些标点基本可以确定是正文，不是人名
SENDER_REJECT = set("，。！？；、,。!?;")

log = get("watcher")

_APPINFO_WARNED = False


@dataclass
class WeChatMessage:
    source: str          # 会话名（微信）/ 通知标题（其他应用）
    sender: str          # 群消息的发送者，单聊和其他应用为空
    content: str         # 消息正文
    received_at: float
    notif_id: int
    app: str = ""        # 来源应用显示名，如「微信」「Microsoft Store」

    @property
    def is_wechat(self) -> bool:
        hay = f"{self.app} {self.source}".lower()
        return any(t in hay for t in WECHAT_TITLES)

    @property
    def display_title(self) -> str:
        if self.sender:
            return f"{self.source} · {self.sender}"
        # 非微信应用把应用名带出来，否则光看标题不知道是谁发的
        if self.app and not self.is_wechat:
            return f"{self.app} · {self.source}"
        return self.source


def _extract_texts(notif) -> list[str]:
    """从通知对象里取出文本行。"""
    try:
        binding = notif.notification.visual.get_binding("ToastGeneric")
    except Exception:
        binding = None
    if binding is None:
        try:
            bindings = notif.notification.visual.bindings
            binding = bindings[0] if bindings else None
        except Exception:
            binding = None
    if binding is None:
        return []
    try:
        return [(t.text or "").strip() for t in binding.get_text_elements() if (t.text or "").strip()]
    except Exception:
        return []


def app_identity(notif) -> tuple[str, str]:
    """取通知所属应用的 (AUMID, 显示名)。

    需要 winrt-Windows.ApplicationModel 投影包；缺了就返回空，
    调用方会退回「看第一行是不是微信」的旧规则。
    """
    global _APPINFO_WARNED

    try:
        info = notif.app_info
    except Exception as e:
        # 只提醒一次，避免每秒刷一条日志
        if not _APPINFO_WARNED:
            _APPINFO_WARNED = True
            log.warning(
                "读不到通知的应用标识（%s），只能靠首行猜来源应用，多应用监听可能失效", e
            )
        return "", ""
    if info is None:
        return "", ""

    aumid = name = ""
    try:
        aumid = (info.app_user_model_id or "").strip()
    except Exception:
        pass
    try:
        display = info.display_info
        if display is not None:
            name = (display.display_name or "").strip()
    except Exception:
        pass
    return aumid, name


def _looks_like_wechat(*fields: str) -> bool:
    hay = " ".join(f for f in fields if f).lower()
    return any(t in hay for t in WECHAT_TITLES)


def _appinfo_available() -> bool:
    """打包后确认 ApplicationModel 投影模块在不在，缺了多应用监听会退化成只认微信。"""
    try:
        import winrt.windows.applicationmodel  # noqa: F401
        return True
    except Exception:
        return False


def parse_notification(texts: list[str], notif_id: int,
                       app_name: str = "") -> Optional[WeChatMessage]:
    """把一条 Toast 的文本行解析成消息对象；解析不出来返回 None。

    微信是「应用名 / 会话名 / 发送者 : 正文」三段式，
    其他应用是「标题 / 正文」两段式，这里分开处理。
    """
    if not texts:
        return None

    if _looks_like_wechat(app_name) or _looks_like_wechat(texts[0]):
        return _parse_wechat(texts, notif_id, app_name)
    return _parse_generic(texts, notif_id, app_name)


def _parse_wechat(texts: list[str], notif_id: int, app_name: str) -> Optional[WeChatMessage]:
    if len(texts) < 2:
        return None

    # 正常情况第一行是「微信」；如果 app_info 已经确认是微信但首行是别的，就整体前移
    offset = 1 if _looks_like_wechat(texts[0]) else 0
    source = texts[offset] if len(texts) > offset else ""
    body = texts[offset + 1] if len(texts) > offset + 1 else ""
    sender = ""

    if body:
        m = SENDER_SPLIT.match(body)
        if m:
            candidate = m.group(1).strip()
            # 名字里不该出现句读标点，出现了说明整行都是正文
            if candidate and not (SENDER_REJECT & set(candidate)):
                sender, body = candidate, m.group(2).strip()

    return WeChatMessage(
        source=source,
        sender=sender,
        content=body,
        received_at=time.time(),
        notif_id=notif_id,
        app=app_name or "微信",
    )


def _parse_generic(texts: list[str], notif_id: int, app_name: str) -> Optional[WeChatMessage]:
    source = texts[0]
    content = "\n".join(t for t in texts[1:] if t)

    return WeChatMessage(
        source=source,
        sender="",
        content=content,
        received_at=time.time(),
        notif_id=notif_id,
        app=app_name or source,
    )


class WeChatWatcher:
    """轮询通知中心，发现新消息时回调 on_message。"""

    def __init__(
        self,
        on_message: Callable[[WeChatMessage], None],
        on_status: Optional[Callable[[str], None]] = None,
        poll_interval: float = 1.0,
        dedup_window: float = 4.0,
        ignore_sources: Optional[list[str]] = None,
        enabled_apps: Optional[list[dict]] = None,
    ):
        self._on_message = on_message
        self._on_status = on_status or (lambda s: None)
        self._poll_interval = poll_interval
        self._dedup_window = dedup_window
        self._ignore_sources = set(ignore_sources or [])
        self._enabled_apps: list[dict] = list(enabled_apps or [])

        self._seen: OrderedDict[int, str] = OrderedDict()
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="wx-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---------- 运行期热更新（设置面板改完立即生效，不必重启） ----------
    def set_poll_interval(self, seconds: float) -> None:
        self._poll_interval = max(0.2, float(seconds))

    def set_ignore_sources(self, names: list[str]) -> None:
        self._ignore_sources = {str(n).strip() for n in (names or []) if str(n).strip()}

    def set_enabled_apps(self, apps: list[dict]) -> None:
        self._enabled_apps = list(apps or [])
        log.info("监听应用已更新: %s",
                 "、".join(a.get("name", "?") for a in self._enabled_apps) or "（无）")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------- 应用过滤 ----------
    def app_enabled(self, aumid: str, app_name: str, texts: list[str]) -> bool:
        """这条通知的来源应用是否在监听范围内。

        只在 AUMID / 显示名里匹配，不拿正文去匹配，
        否则正文里出现「微信」两个字就会被误判。
        """
        if not self._enabled_apps:
            return False

        hay = " ".join(x for x in (aumid, app_name) if x).lower()
        if not hay:
            # 拿不到应用标识时退回旧规则：只看第一行是不是微信
            hay = (texts[0] if texts else "").lower()

        for app in self._enabled_apps:
            for pat in app.get("match", []):
                if pat and pat in hay:
                    return True
        return False

    # ---------- 主循环 ----------
    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run(self) -> None:
        listener = UserNotificationListener.current
        status = listener.get_access_status()

        if status != UserNotificationListenerAccessStatus.ALLOWED:
            self._on_status("requesting_access")
            log.info("尚未获得通知访问权限，正在请求…")
            status = await listener.request_access_async()

        if status != UserNotificationListenerAccessStatus.ALLOWED:
            log.warning("通知访问被拒绝（status=%s）", status)
            self._on_status("access_denied")
            return

        self._on_status("watching")
        log.info("通知监听已启动，轮询间隔 %.2fs", self._poll_interval)
        log.info("应用标识读取: %s", "可用" if _appinfo_available() else "不可用（只能识别微信）")

        # 首次读取只建立基线，避免把历史通知全部弹出来
        try:
            for n in await listener.get_notifications_async(NotificationKinds.TOAST):
                self._seen[n.id] = "|".join(_extract_texts(n))
            log.info("基线建立完成，已有 %d 条通知", len(self._seen))
        except Exception as e:
            log.warning("建立通知基线失败: %s", e)

        fail_count = 0
        while not self._stop.is_set():
            try:
                notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
                fail_count = 0
                for n in notifs:
                    self._handle(n)
            except Exception as e:
                # 通知服务偶发不可用（微信重启、系统通知服务抖动），忽略并继续。
                # 连续失败才记一条，避免日志被刷爆。
                fail_count += 1
                if fail_count == 1 or fail_count % 60 == 0:
                    log.warning("读取通知中心失败（第 %d 次）: %s", fail_count, e)
            await asyncio.sleep(self._poll_interval)

    def _handle(self, n) -> None:
        texts = _extract_texts(n)
        if not texts:
            return

        signature = "|".join(texts)
        previous = self._seen.get(n.id)
        self._seen[n.id] = signature
        self._seen.move_to_end(n.id)

        # 超出缓存上限的老记录直接丢弃
        while len(self._seen) > 800:
            self._seen.popitem(last=False)

        if previous == signature:
            return

        aumid, app_name = app_identity(n)
        if not self.app_enabled(aumid, app_name, texts):
            log.debug("应用不在监听范围，已跳过: aumid=%r name=%r text0=%r",
                      aumid, app_name, texts[0])
            return

        msg = parse_notification(texts, n.id, app_name or aumid)
        if msg is None:
            return
        if msg.source in self._ignore_sources:
            log.debug("免打扰会话，已跳过: %s", msg.source)
            return
        if self._is_duplicate(msg):
            log.debug("重复消息，已跳过: %s", msg.display_title)
            return

        log.info("收到消息 [%s] %s", msg.display_title, msg.content[:60])
        self._on_message(msg)

    def _is_duplicate(self, msg: WeChatMessage) -> bool:
        key = f"{msg.app}|{msg.source}|{msg.sender}|{msg.content}"
        now = time.time()

        # 清掉过期的去重记录
        while self._recent:
            first_key, ts = next(iter(self._recent.items()))
            if now - ts > self._dedup_window:
                self._recent.popitem(last=False)
            else:
                break

        if key in self._recent:
            return True
        self._recent[key] = now
        return False
