"""识别本机「设置 → 系统 → 通知」里出现过通知的应用。

思路
----
PC 微信这类 Win32 程序根本不往消息中心发通知，所以「按进程枚举」没有意义。
真正有意义的名单是 Windows 自己维护的注册表名单：

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings

下面每个子键就是一个 AUMID（应用用户模型 ID），只有发过通知的应用才会出现。
名字解析分四级，越靠前越准：

1. 学习缓存 —— 程序运行时从通知 ``app_info.display_name`` 拿到，系统本地化过的
2. 内置映射 —— 常见软件的中文名
3. 注册表 ``AppUserModelId\\<AUMID>\\DisplayName`` —— 少数软件会写
4. 兜底美化 —— 把 ``Company.Product_8wekyb3d8bbwe!App`` 拆成可读英文
"""

from __future__ import annotations

import re
from typing import Iterable

try:
    import winreg
except ImportError:  # 非 Windows 平台，全部功能降级
    winreg = None  # type: ignore[assignment]

# ---------------------------------------------------------------- 注册表路径

#: 「设置 → 通知」里出现过的应用，子键名就是 AUMID
NOTIFICATION_SETTINGS_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
)
#: 少量软件会把显示名写在这里
AUMID_CLASSES_KEY = r"Software\Classes\AppUserModelId"

#: 手机连接的 AUMID 前缀（所有手机 App 转发都走它）
PHONE_LINK_AUMID = "microsoft.yourphone"

# ---------------------------------------------------------------- 内置中文名
#
# 键统一小写、去掉 ``!`` 之后的部分。
# 值即设置界面里显示的中文名。

KNOWN_NAMES: dict[str, str] = {
    # 社交 / 通讯
    "qq": "QQ",
    "wechat": "微信",
    "telegram.telegramdesktop": "Telegram",
    "microsoft.yourphone": "手机连接",
    "dingtalk": "钉钉",
    "lark": "飞书",
    "feishu": "飞书",
    "wemeet": "腾讯会议",
    "tencent.meeting": "腾讯会议",
    "slack": "Slack",
    "discord": "Discord",
    "microsoft.teams": "Microsoft Teams",
    "mstsc": "远程桌面",
    # 浏览器
    "msedge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "brave": "Brave",
    "quark": "夸克",
    "360se": "360 浏览器",
    # 开发工具
    "code": "Visual Studio Code",
    "devenv": "Visual Studio",
    "pycharm": "PyCharm",
    "idea": "IntelliJ IDEA",
    "clion": "CLion",
    "goland": "GoLand",
    "webstorm": "WebStorm",
    "rider": "Rider",
    "sublime_text": "Sublime Text",
    "windows terminal": "Windows 终端",
    "windowsterminal": "Windows 终端",
    "microsoft.windowsterminal": "Windows 终端",
    "githubdesktop": "GitHub Desktop",
    "git": "Git",
    "navicat": "Navicat",
    "datagrip": "DataGrip",
    "postman": "Postman",
    "traecn": "Trae",
    "bytedance.traecn": "Trae",
    "workbuddy.workbuddyai": "WorkBuddy",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "docker desktop": "Docker Desktop",
    "dockerdesktop": "Docker Desktop",
    # 终端 / 服务器
    "xshell": "Xshell",
    "xftp": "Xftp",
    "securecrt": "SecureCRT",
    "winscp": "WinSCP",
    "putty": "PuTTY",
    "mobaxterm": "MobaXterm",
    "finalshell": "FinalShell",
    "electerm": "Electerm",
    "tabby": "Tabby",
    # 下载 / 工具
    "thunder": "迅雷",
    "motrix": "Motrix",
    "idm": "Internet Download Manager",
    "everything": "Everything",
    "listary": "Listary",
    "uTools": "uTools",
    "powertoys": "PowerToys",
    "snipaste": "Snipaste",
    "sharex": "ShareX",
    "obs": "OBS Studio",
    "bandizip": "Bandizip",
    "360zip": "360 压缩",
    "winrar": "WinRAR",
    "7zfm": "7-Zip",
    "notepad": "记事本",
    "notepad++": "Notepad++",
    "typora": "Typora",
    "obsidian": "Obsidian",
    # 影音 / 图像
    "cloudmusic": "网易云音乐",
    "qqmusic": "QQ 音乐",
    "kugou": "酷狗音乐",
    "potplayer": "PotPlayer",
    "vlc": "VLC",
    "mpc-hc": "MPC-HC",
    "photoshop": "Photoshop",
    "illustrator": "Illustrator",
    "lightroom": "Lightroom",
    "figma": "Figma",
    "mastergo": "MasterGo",
    "lanhu": "蓝湖",
    # 游戏平台
    "steam": "Steam",
    "epicgameslauncher": "Epic Games",
    "wegame": "WeGame",
    "battlenet": "战网",
    # 输入法 / 系统组件
    "sogouinput": "搜狗输入法",
    "qqpinyin": "QQ 输入法",
    "baiduinput": "百度输入法",
    "microsoft.ime": "微软输入法",
    # 联想 / 品牌预装
    "lenovosmartmeeting": "联想智能会议",
    "lenovo": "联想电脑管家",
    "lenovovantage": "联想电脑管家",
    "aispeechaudionotify": "思必驰语音",
    "ai智能场景": "联想智能场景",
    # 下载 / 网盘 / 杂项
    "motrix": "Motrix",
    "app.motrix.native": "Motrix",
    "chatbox": "Chatbox",
    "xyz.chatboxapp.app": "Chatbox",
    "ariang": "AriaNg",
    "electron.app.arianggui": "AriaNg",
    "a-volute.nahimic": "Nahimic 音效",
    "nahimic": "Nahimic 音效",
    "microsoft.skydrive.desktop": "OneDrive",
    "microsoft.screensketch": "截图和草图",
    "microsoft.windowsalarms": "闹钟和时钟",
    "microsoft.windowsstore": "Microsoft Store",
    "clash": "Clash",
    "clashverge": "Clash Verge",
    "verge": "Clash Verge",
    "v2rayn": "v2rayN",
    "surge": "Surge",
    "qBittorrent": "qBittorrent",
    "freedownloadmanager": "Free Download Manager",
    "sunlogin": "向日葵远程控制",
    "todesk": "ToDesk",
    "teamviewer": "TeamViewer",
    "anydesk": "AnyDesk",
    "jumpserver": "JumpServer",
    "wps": "WPS Office",
    "kingsoft": "WPS Office",
}

#: 这些 AUMID 是系统托盘图标的哈希派生项，人看不懂，也不代表一个真实软件
_JUNK_PREFIXES = (
    "notifyicongeneratedaumid_",
    "windows.systemtoast.",
    "windows.actioncenter.",
    "windows.defender.",
    "windows.immersivecontrolpanel",
    "windows.ui.",
)

#: 纯 GUID 形式的 AUMID（传统 Win32 未注册应用，或带 exe 路径的驱动项）。
#: 既匹配带花括号的，也匹配手机连接注册表键尾巴上那种裸 GUID。
_GUID_RE = re.compile(
    r"^\{?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}?", re.I
)

#: 手机连接转发时，每条通知的 AUMID 尾巴上带着手机 App 的包名。
#: 认得出就显示「手机连接 · 微信」，认不出就显示包名最后一段。
PHONE_APP_NAMES: dict[str, str] = {
    "com.tencent.xin": "微信",
    "com.tencent.mqq": "QQ",
    "com.tencent.tim": "TIM",
    "com.alipay.iphoneclient": "支付宝",
    "com.taobao.tmallapp": "手机淘宝",
    "com.taobao.fleamarket": "闲鱼",
    "com.jingdong.iphone": "京东",
    "com.xiaojukeji.didi": "滴滴出行",
    "com.sdu.didi.psnger": "滴滴出行",
    "com.ct.client": "中国电信",
    "com.10010.lifepay": "中国联通",
    "com.apple.mobilephone": "电话",
    "com.apple.mobilesms": "信息",
    "com.apple.shortcuts": "快捷指令",
    "com.apple.preferences": "设置",
    "com.apple.testflight": "TestFlight",
    "com.apple.mobilemail": "邮件",
    "com.apple.facetime": "FaceTime",
    "cn.com.petrochina.weworkgov": "中石油移动办公",
    "cn.yingmi.qieman-ios": "且慢",
    "com.kiwik.usmartgo": "什么值得买",
    "com.xinchuzu.driver": "鑫租房司机端",
    "com.yabin.chiyaozhushou": "吃药助手",
    "net.colorfulclouds.app.pro": "心光",
    "com.dancesuite.dance.ka.kazsy73qyq": "舞蹈 App",
}


# ---------------------------------------------------------------- 工具函数

def _norm(aumid: str) -> str:
    """归一化：小写、去掉包族后缀和 ``!App`` 段。"""
    key = aumid.split("!")[0].strip().lower()
    # 去掉 _8wekyb3d8bbwe / _cw5n1h2txyewy 这类发布者后缀
    key = re.sub(r"_[0-9a-z]{8,}$", "", key, flags=re.I)
    return key


def is_junk_aumid(aumid: str) -> bool:
    """托盘哈希项、系统 Toast、GUID 项都不该出现在候选列表里。"""
    low = aumid.lower()
    if any(low.startswith(p) for p in _JUNK_PREFIXES):
        return True
    if _GUID_RE.match(aumid):
        return True
    return False


def phone_app_label(aumid: str) -> str:
    """手机连接的 AUMID 尾巴上带着手机 App 包名，尽量翻译成人话。

    ``Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.tencent.xin``
    → ``微信``；认不出的包名退回最后一段。
    """
    if "yourphonenotifications_" not in aumid.lower():
        return ""
    bundle = aumid.split("YourPhoneNotifications_", 1)[1].split("!")[0].strip()
    if not bundle or bundle.lower() == "yourphonesetup":
        return ""
    # 有些键后面挂的是 GUID 而不是包名，那是历史遗留，跳过
    if _GUID_RE.match(bundle):
        return ""
    low = bundle.lower()
    if low in PHONE_APP_NAMES:
        return PHONE_APP_NAMES[low]
    # 前缀匹配：cn.com.petrochina.weworkgovPrqZE 这类带随机尾巴的
    for k, v in PHONE_APP_NAMES.items():
        if low.startswith(k):
            return v
    # 退回包名最后一段，去掉 -ios / -android 之类的尾巴
    tail = bundle.rsplit(".", 1)[-1]
    for suffix in ("-ios", "-android", "-ipad"):
        if tail.lower().endswith(suffix):
            tail = tail[: -len(suffix)]
    return tail or bundle


def is_pc_wechat(aumid: str) -> bool:
    """PC 微信不发通知，不该出现在「可监听应用」里，避免误导。"""
    low = aumid.lower()
    return "wechat" in low or "weixin" in low


def beautify(aumid: str) -> str:
    """兜底美化：``Microsoft.YourPhone_8wekyb3d8bbwe!App`` → ``Microsoft YourPhone``。"""
    base = aumid.split("!")[0].strip()
    base = re.sub(r"_[0-9a-z]{8,}$", "", base, flags=re.I)
    parts = [p for p in re.split(r"[.\s]+", base) if p]
    if not parts:
        return aumid

    # 跳过开头的小写命名空间段（microsoft / bytedance / lenovo 等）
    start = 0
    while start < len(parts) - 1 and parts[start][:1].islower():
        start += 1

    words: list[str] = []
    for part in parts[start:]:
        # CamelCase 拆词：YourPhone → Your Phone
        for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", part):
            if not words or words[-1] != w:
                words.append(w)
    if not words:
        return " ".join(parts)
    return " ".join(words)


# ---------------------------------------------------------------- 注册表读取

def _open_key(path: str):
    if winreg is None:
        return None
    try:
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        return None


def _sub_key_names(key) -> list[str]:
    names: list[str] = []
    if key is None:
        return names
    try:
        count = winreg.QueryInfoKey(key)[0]
    except OSError:
        return names
    for i in range(count):
        try:
            names.append(winreg.EnumKey(key, i))
        except OSError:
            continue
    return names


def _query_value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def list_notification_apps() -> list[str]:
    """枚举「设置 → 通知」里出现过通知的应用 AUMID。

    手机连接在注册表里会为每个转发的手机 App 各建一个键，
    显示时折叠成一条「手机连接」，具体转发哪些 App 用 phone_link_apps() 单独看。
    """
    key = _open_key(NOTIFICATION_SETTINGS_KEY)
    if key is None:
        return []
    try:
        out: list[str] = []
        phone_link_canonical = ""
        for aumid in _sub_key_names(key):
            if not aumid or is_junk_aumid(aumid):
                continue
            if is_pc_wechat(aumid):
                continue
            if is_phone_link_aumid(aumid):
                # 通知里出现的 AUMID 固定是 <Package>!App，直接归一成这个形态，
                # 注册表里那条可能是 YourPhoneSetup 或 YourPhoneNotifications_xxx
                head = aumid.split("!", 1)[0]
                phone_link_canonical = f"{head}!App"
                continue
            if aumid not in out:
                out.append(aumid)
        if phone_link_canonical:
            out.insert(0, phone_link_canonical)
        return out
    finally:
        winreg.CloseKey(key)


def phone_link_apps() -> list[tuple[str, str]]:
    """列出手机连接正在转发通知的手机 App，返回 [(中文名, AUMID)]，按名字排序。

    AUMID 尾巴上带着手机 App 的包名，例如
    ``...!YourPhoneNotifications_com.tencent.xin`` 就是微信。
    """
    key = _open_key(NOTIFICATION_SETTINGS_KEY)
    if key is None:
        return []
    try:
        rows: list[tuple[str, str]] = []
        for aumid in _sub_key_names(key):
            if not is_phone_link_aumid(aumid):
                continue
            label = phone_app_label(aumid)
            if not label:
                continue
            rows.append((label, aumid))
        rows.sort(key=lambda r: (r[0].lower(), r[1]))
        # 同一个 App 可能有多条（不同 GUID），去重
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for label, aumid in rows:
            if label in seen:
                continue
            seen.add(label)
            out.append((label, aumid))
        return out
    finally:
        winreg.CloseKey(key)


def registry_display_name(aumid: str) -> str:
    """读 ``AppUserModelId\\<AUMID>\\DisplayName``，拿不到返回空串。"""
    key = _open_key(f"{AUMID_CLASSES_KEY}\\{aumid}")
    if key is None:
        return ""
    try:
        for name in ("DisplayName", "DisplayNameResource"):
            val = _query_value(key, name)
            if val and not str(val).startswith("@"):
                return str(val)
    finally:
        winreg.CloseKey(key)
    return ""


def resolve_name(aumid: str, learned: dict | None = None) -> str:
    """把 AUMID 翻译成人能看懂的名字。"""
    learned = learned or {}
    # 1. 运行时学到的（系统本地化过）
    got = learned.get(aumid)
    if got:
        return str(got)
    # 2. 注册表
    reg = registry_display_name(aumid)
    if reg:
        return reg
    # 3. 内置映射
    known = KNOWN_NAMES.get(_norm(aumid))
    if known:
        return known
    # 4. 兜底美化
    return beautify(aumid)


def describe_apps(aumids: Iterable[str], learned: dict | None = None) -> list[dict]:
    """返回 ``[{"aumid":..., "name":...}, ...]``，按名字排序。

    同名不同 AUMID 的（比如同一个音频驱动的两个实例）只留一条，
    否则设置列表里会出现两行一模一样的名字。
    """
    learned = learned or {}
    rows: list[dict] = []
    seen_names: set[str] = set()
    for a in aumids:
        name = resolve_name(a, learned)
        if name in seen_names:
            continue
        seen_names.add(name)
        rows.append({"aumid": a, "name": name})
    rows.sort(key=lambda r: (r["name"].lower(), r["aumid"]))
    return rows


def match_patterns(name: str, aumid: str = "") -> list[str]:
    """给设置列表里的一行生成匹配关键字（小写）。

    ``name`` 是显示名，``aumid`` 是注册表里的原始标识。

    为什么拿 AUMID 而不是显示名的单词：显示名拆词会产生「microsoft」这种
    通用词，勾一个 Microsoft Store 就会把 OneDrive、闹钟、截图工具的通知
    全放进来。AUMID 足够长、足够特异，拿它当子串去匹配最稳。
    """
    pats: list[str] = []

    def add(s: str) -> None:
        s = (s or "").strip().lower()
        if s and s not in pats:
            pats.append(s)

    if aumid:
        # 去掉发布者后缀和 !App 段，剩下的包名同时能匹配
        # 注册表里的 ByteDance.TraeCN 和通知里的 ByteDance.TraeCN_8wekyb3d8bbwe!App
        add(_norm(aumid))
        add(aumid.lower())
    add(name)
    # 中文显示名去掉空格再要一份，避免「截图和草图」被写成「截图 和 草图」就对不上
    if name:
        add(name.replace(" ", ""))
    # 兜底：一个都没生成出来时至少留个名字，否则这一行勾了也永远匹配不到
    return pats or ([name.lower()] if name else [])


# ---------------------------------------------------------------- 手机连接检测

def _all_registry_aumids() -> list[str]:
    """原始枚举，不做任何折叠和过滤。"""
    key = _open_key(NOTIFICATION_SETTINGS_KEY)
    if key is None:
        return []
    try:
        return _sub_key_names(key)
    finally:
        winreg.CloseKey(key)


def phone_link_status() -> str:
    """检测手机连接（Phone Link）的安装 / 配对状态。

    返回三种状态之一：

    - ``"none"``   没安装
    - ``"installed"`` 装了但没配对（或配对后没在转发通知）
    - ``"active"`` 已经在转发手机 App 的通知
    """
    aumids = [a.lower() for a in _all_registry_aumids()]
    if not any(a.startswith(PHONE_LINK_AUMID) for a in aumids):
        return "none"
    # 每条转发的手机 App 都会有一个 YourPhoneNotifications_<包名> 键
    if any("yourphonenotifications_" in a for a in aumids):
        return "active"
    return "installed"


def is_phone_link_aumid(aumid: str) -> bool:
    return aumid.lower().startswith(PHONE_LINK_AUMID)
