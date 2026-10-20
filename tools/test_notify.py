# -*- coding: utf-8 -*-
"""测试 Windows 通知监听：授权状态 + 读取当前通知中心里的微信通知。"""
import asyncio

from winrt.windows.ui.notifications import NotificationKinds
from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)


async def main():
    listener = UserNotificationListener.current

    status = listener.get_access_status()
    print("initial access status:", status)

    if status != UserNotificationListenerAccessStatus.ALLOWED:
        print("requesting access ...")
        status = await listener.request_access_async()
        print("after request:", status)

    if status != UserNotificationListenerAccessStatus.ALLOWED:
        print("!! ACCESS NOT GRANTED, cannot read notifications")
        return

    notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    print(f"\n==== {len(notifs)} toast notifications in center ====\n")

    for n in notifs:
        try:
            app = n.app_info.display_info.display_name
        except Exception:
            app = "?"
        try:
            t = n.notification.visual.get_binding("ToastGeneric")
            texts = [x.text for x in t.get_text_elements()] if t else []
        except Exception as e:
            texts = [f"<parse error {e}>"]
        print(f"[app={app}] id={n.id} created={n.creation_time}")
        for i, tx in enumerate(texts):
            print(f"    text{i}: {tx!r}")
        print()


asyncio.run(main())
