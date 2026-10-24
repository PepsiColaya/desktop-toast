# -*- coding: utf-8 -*-
"""监听 Windows 通知中心，捕获用户勾选的应用的新消息。

通过 UserNotificationListener 读取通知中心的 Toast，不注入任何进程、不读它们的数据库。

注意：这条路只对「会把消息推送到 Windows 通知中心」的应用有效。
PC 微信 4.x 属于不推送的那一类（实测它的通知处理器数为 0），
具体原因和可选的替代方案见 README 的「案例：微信」一节。

监听哪些应用由 config 的 enabled_apps 决定，默认只有「手机连接」
（手机上的通知经它转发过来，微信等 App 的消息也是这么进来的）。
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

# 「手机连接」（Phone Link）把手机上的通知转发到电脑时，所有 App 共用同一个 AUMID
# 和显示名，真实来源只写在通知首行。命中这些特征时要把首行一起纳入匹配。
PHONE_LINK_HINTS = ("microsoft.yourphone", "手机连接", "phone link")

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
    aumid: str = ""      # 来源应用标识，点击卡片时用来唤起对应应用

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
                       app_name: str = "", aumid: str = "") -> Optional[WeChatMessage]:
    """把一条 Toast 的文本行解析成消息对象；解析不出来返回 None。

    微信是「应用名 / 会话名 / 发送者 : 正文」三段式，
    其他应用是「标题 / 正文」两段式，这里分开处理。
    """
    if not texts:
        return None

    if _looks_like_wechat(app_name) or _looks_like_wechat(texts[0]):
        return _parse_wechat(texts, notif_id, app_name, aumid)
    return _parse_generic(texts, notif_id, app_name, aumid)


def _parse_wechat(texts: list[str], notif_id: int, app_name: str,
                  aumid: str = "") -> Optional[WeChatMessage]:
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
        aumid=aumid,
    )


def _parse_generic(texts: list[str], notif_id: int, app_name: str,
                   aumid: str = "") -> Optional[WeChatMessage]:
    source = texts[0]
    content = "\n".join(t for t in texts[1:] if t)

    return WeChatMessage(
        source=source,
        sender="",
        content=content,
        received_at=time.time(),
        notif_id=notif_id,
        app=app_name or source,
        aumid=aumid,
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
        on_app_learned: Optional[Callable[[str, str], None]] = None,
        phone_apps: Optional[list[str]] = None,
        phone_known: Optional[list[str]] = None,
        on_phone_app_learned: Optional[Callable[[str], None]] = None,
    ):
        self._on_message = on_message
        self._on_status = on_status or (lambda s: None)
        self._poll_interval = poll_interval
        self._dedup_window = dedup_window
        self._ignore_sources = set(ignore_sources or [])
        self._enabled_apps: list[dict] = list(enabled_apps or [])
        # 学到新的 AUMID -> 显示名 时回调，供设置界面把英文名换成中文名
        self._on_app_learned = on_app_learned
        # 手机连接子项过滤：None=全收，[]=全不收，[...]=只收这些手机 App
        self._phone_apps = None if phone_apps is None else {
            str(x).strip().lower() for x in phone_apps if str(x).strip()
        }
        # 本机手机连接正在转发的手机 App 名，用来判断首行认不认得出来
        self._phone_known = {str(x).strip().lower() for x in (phone_known or []) if str(x).strip()}
        # 从通知首行学到新的手机 App 名时回调，供设置界面补进列表
        self._on_phone_app_learned = on_phone_app_learned

        self._seen: OrderedDict[int, str] = OrderedDict()
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._learned: dict[str, str] = {}
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

    def set_phone_apps(
        self,
        phone_apps: Optional[list[str]],
        phone_known: Optional[list[str]] = None,
    ) -> None:
        """设置「手机连接」下面勾了哪些手机 App。

        ``None`` = 不过滤（手机转发来的全收），``[]`` = 一个都不收。
        ``phone_known`` 是本机手机连接正在转发的 App 名，用来判断通知首行认不认得出来。
        """
        self._phone_apps = None if phone_apps is None else {
            str(x).strip().lower() for x in phone_apps if str(x).strip()
        }
        if phone_known is not None:
            self._phone_known = {
                str(x).strip().lower() for x in phone_known if str(x).strip()
            }
        log.info("手机 App 过滤: %s",
                 "不过滤" if self._phone_apps is None
                 else ("、".join(sorted(self._phone_apps)) or "（全不勾）"))

    def set_phone_known(self, names: list[str]) -> None:
        """更新「已知手机 App 名」，不影响勾选状态。"""
        self._phone_known = {str(x).strip().lower() for x in (names or []) if str(x).strip()}

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

        # 手机连接转发：AUMID 和显示名都是「手机连接」，光看这两个字段分不出是微信
        # 还是别的 App，真实来源在首行（微信 / 快捷指令 / TestFlight…）。
        #
        # 这里必须单独一条路走到底，不能把首行拼进 hay 再去和所有应用比：
        # PC 版 QQ 的匹配串就是「qq」，手机上来的 QQ 消息首行也叫「QQ」，
        # 一比就把「取消手机连接」顶回来了——这正是「取消了还在弹」的原因。
        if bool(texts) and any(h in hay for h in PHONE_LINK_HINTS):
            if not self._phone_gateway_enabled():
                return False
            return self._phone_app_allowed(texts)

        if not hay:
            # 拿不到应用标识时退回旧规则：只看第一行是不是微信
            hay = (texts[0] if texts else "").lower()

        for app in self._enabled_apps:
            for pat in app.get("match", []):
                if pat and pat in hay:
                    return True
        return False

    def _phone_gateway_enabled(self) -> bool:
        """「手机连接」这一项本身在不在监听名单里。

        它是所有手机通知的唯一入口：没勾它，手机转发来的一律不放行，
        哪怕名单里还勾着同名的 PC 应用（比如 PC 版 QQ）。
        """
        for app in self._enabled_apps:
            hay = f"{app.get('aumid') or ''} {app.get('name') or ''}".lower()
            if any(h in hay for h in PHONE_LINK_HINTS):
                return True
        return False

    def _phone_app_allowed(self, texts: list[str]) -> bool:
        """手机转发来的这条通知，对应的手机 App 是否在勾选范围内。

        名单是白名单：勾了哪些就只收哪些。认不出来的不再无条件放行——
        那样「只勾微信」就成了空话，手机上随便哪个 App 都能弹出来。
        认不出来的会在到达时被记进 phone_known（见 _learn_phone_app），
        所以第一次之后就能在设置里看到并单独勾选。
        """
        if self._phone_apps is None:
            return True
        if not self._phone_apps:
            # 一个都没勾 = 手机 App 全不收
            return False
        if not texts:
            return True
        first = texts[0].strip().lower()
        if not first:
            return True

        # 先认完全相同的，避免「QQ」把「QQ音乐」的勾选状态抢走
        if first in self._phone_known:
            return first in self._phone_apps
        # 再按最长匹配兜底（「QQ邮箱 · 新邮件」这种首行带后缀的）
        cands = [l for l in self._phone_known if l and (l in first or first in l)]
        if cands:
            return max(cands, key=len) in self._phone_apps
        return False

    def _is_phone_source(self, aumid: str, app_name: str) -> bool:
        hay = f"{aumid or ''} {app_name or ''}".lower()
        return any(h in hay for h in PHONE_LINK_HINTS)

    def _learn_phone_app(self, name: str) -> None:
        """从通知首行学一个手机 App 名。

        注册表那份列表会漏（名字对不上、企业自建应用没注册），
        这里按真实通知补，学到就回调给主程序存进配置。
        """
        name = (name or "").strip()
        if not name or len(name) > 40:
            return
        low = name.lower()
        if low in self._phone_known:
            return
        self._phone_known.add(low)
        log.info("学到手机 App 名: %s", name)
        if self._on_phone_app_learned is not None:
            try:
                self._on_phone_app_learned(name)
            except Exception as e:
                log.debug("手机 App 名学习回调失败: %s", e)

    # ---------- 主循环 ----------
    def _learn_app_name(self, aumid: str, app_name: str) -> None:
        """记住 AUMID 对应的系统显示名，设置界面就能显示中文名而不是进程名。

        只在第一次见到某个 AUMID 时回调，避免每次轮询都触发保存。
        """
        if not aumid or not app_name:
            return
        if self._learned.get(aumid) == app_name:
            return
        self._learned[aumid] = app_name
        if self._on_app_learned is not None:
            try:
                self._on_app_learned(aumid, app_name)
            except Exception as e:
                log.debug("应用名学习回调失败: %s", e)

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
                texts = _extract_texts(n)
                self._seen[n.id] = "|".join(texts)
                # 顺手把历史里的手机 App 名学一遍：白名单要勾得上，
                # 就得先把名字凑齐，否则升级后第一次收到的 App 会被默默挡掉
                if texts:
                    aumid, name = app_identity(n)
                    if self._is_phone_source(aumid, name):
                        self._learn_phone_app(texts[0])
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
        self._learn_app_name(aumid, app_name)
        # 手机转发来的先学首行的 App 名，再判过滤：
        # 这样新 App 第一次到达就能被记进名单，之后勾不勾才管得住
        if self._is_phone_source(aumid, app_name):
            self._learn_phone_app(texts[0])
        if not self.app_enabled(aumid, app_name, texts):
            log.debug("应用不在监听范围，已跳过: aumid=%r name=%r text0=%r",
                      aumid, app_name, texts[0])
            return

        msg = parse_notification(texts, n.id, app_name or aumid, aumid)
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
