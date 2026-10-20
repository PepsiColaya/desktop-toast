# -*- coding: utf-8 -*-
"""监听 Windows 通知中心，捕获微信新消息。

微信 4.x 是 Qt 自绘渲染，UIA 控件树为空，无法直接读取会话列表；
但微信会把新消息推送到 Windows 通知中心，这里通过
UserNotificationListener 读取，无需注入微信进程、无需读取数据库。
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

WECHAT_TITLES = ("微信", "wechat")

# 群消息格式为 "发送者 : 内容"，发送者名字通常很短
SENDER_SPLIT = re.compile(r"^(.{1,24}?)\s*[:：]\s*(.+)$", re.S)


@dataclass
class WeChatMessage:
    source: str          # 会话名（群名 / 联系人）
    sender: str          # 群消息的发送者，单聊时为空
    content: str         # 消息正文
    received_at: float
    notif_id: int

    @property
    def display_title(self) -> str:
        return f"{self.source} · {self.sender}" if self.sender else self.source


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


def parse_wechat(texts: list[str], notif_id: int) -> Optional[WeChatMessage]:
    """把微信 Toast 的文本行解析成消息对象；非微信通知返回 None。"""
    if len(texts) < 2:
        return None
    if not texts[0].lower().startswith(WECHAT_TITLES):
        return None

    source = texts[1]
    body = texts[2] if len(texts) > 2 else ""
    sender = ""

    if body:
        m = SENDER_SPLIT.match(body)
        if m:
            sender, body = m.group(1).strip(), m.group(2).strip()

    return WeChatMessage(
        source=source,
        sender=sender,
        content=body,
        received_at=time.time(),
        notif_id=notif_id,
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
    ):
        self._on_message = on_message
        self._on_status = on_status or (lambda s: None)
        self._poll_interval = poll_interval
        self._dedup_window = dedup_window
        self._ignore_sources = set(ignore_sources or [])

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

    # ---------- 主循环 ----------
    async def _run(self) -> None:
        listener = UserNotificationListener.current
        status = listener.get_access_status()

        if status != UserNotificationListenerAccessStatus.ALLOWED:
            self._on_status("requesting_access")
            status = await listener.request_access_async()

        if status != UserNotificationListenerAccessStatus.ALLOWED:
            self._on_status("access_denied")
            return

        self._on_status("watching")

        # 首次读取只建立基线，避免把历史通知全部弹出来
        try:
            for n in await listener.get_notifications_async(NotificationKinds.TOAST):
                self._seen[n.id] = "|".join(_extract_texts(n))
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
                for n in notifs:
                    self._handle(n)
            except Exception:
                # 通知服务偶发不可用，忽略并继续
                pass
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

        msg = parse_wechat(texts, n.id)
        if msg is None:
            return
        if msg.source in self._ignore_sources:
            return
        if self._is_duplicate(msg):
            return

        self._on_message(msg)

    def _is_duplicate(self, msg: WeChatMessage) -> bool:
        key = f"{msg.source}|{msg.sender}|{msg.content}"
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
