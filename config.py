# -*- coding: utf-8 -*-
"""配置的默认值、读取、保存与范围校验。"""
from __future__ import annotations

import json
import os
import shutil
import sys

APP_NAME = "DesktopToast"

# 改名前的目录名。老用户升级时把整个目录搬过来，配置和日志都不用重设
LEGACY_APP_NAME = "WeChatToast"

# 老配置里预置过、但实际收不到通知的条目（PC 微信不往消息中心发消息）。
# 规范化时按 key 丢弃，避免设置界面出现勾了也没用的幽灵项。
GHOST_APP_KEYS = {"wechat", "微信"}


def default_apps() -> list[dict]:
    """默认监听「手机连接」。

    可监听的应用**只取 Windows「设置 → 系统 → 通知」里出现过的应用**
    （注册表 Notifications\\Settings 下的 AUMID），这里不再预置「微信」：
    PC 微信从来不往消息中心发通知，它在系统通知列表里根本不存在，
    留在名单里只会让人以为勾了就能收微信，实际一条也收不到。

    微信消息是「手机连接」把手机通知转发过来的，所以默认勾选手机连接。
    转发来的通知首行是手机 App 名（微信 / 快捷指令 / TestFlight…），
    watcher.app_enabled 会把首行一起纳入匹配（见 PHONE_LINK_HINTS）。
    """
    return [{
        "key": "microsoft.yourphone_8wekyb3d8bbwe!app",
        "name": "手机连接",
        "aumid": "Microsoft.YourPhone_8wekyb3d8bbwe!App",
        "match": ["microsoft.yourphone", "手机连接", "phone link"],
    }]


DEFAULT_CONFIG: dict = {
    # ---- 外观 ----
    "theme": "dark",                 # dark / light
    "font_family": "Microsoft YaHei UI",
    "card_width": 340,               # 卡片宽度 px
    "scale": 1.0,                    # 字号与内边距缩放
    "radius": 14,                    # 圆角 px
    "shadow": 16,                    # 阴影扩散范围 px
    "opacity": 0.96,                 # 整体不透明度
    "gap": 8,                        # 卡片间距 px
    # ---- 位置 ----
    "position": "top-right",         # top-right / top-left / bottom-right / bottom-left
    "margin": 22,                    # 距屏幕边缘 px
    "screen": "cursor",              # cursor=跟随鼠标所在屏幕，primary=主屏
    # ---- 行为 ----
    "duration_ms": 3000,             # 停留时长
    "max_visible": 3,                # 同屏最多几张
    "fade_in_ms": 170,
    "fade_out_ms": 280,
    "hover_pause": True,             # 鼠标悬停时暂停倒计时
    "click_to_open_wechat": True,
    "merge_same_source": True,       # 同一会话连续消息合并成一张卡片
    "show_content": True,            # 卡片是否显示消息正文；关掉只显示「有一条新消息」
    "poll_interval_ms": 1000,        # 通知轮询间隔
    "ignore_sources": [],            # 不提醒的会话名
    "avatar_dir": "",                # 头像目录，留空则用程序目录下的 avatars
    # ---- 监听范围 ----
    "enabled_apps": default_apps(),  # 只提醒这些应用的通知
    # AUMID -> 中文名 的学习缓存，运行时从通知里自动补全
    "app_names": {},
    # ---- 启动 ----
    "autostart": False,              # 开机自启（写 HKCU Run 注册表项）
    # ---- 设置面板布局 ----
    "left_width": 540,               # 设置窗口左栏宽度，中间分割线可拖
}

# 数值型配置的合法区间，读取和保存时都会夹紧
RANGES: dict = {
    "card_width": (240, 560),
    "scale": (0.8, 1.5),
    "radius": (0, 24),
    "shadow": (0, 30),
    "opacity": (0.4, 1.0),
    "gap": (0, 24),
    "margin": (6, 120),
    "duration_ms": (800, 20000),
    "max_visible": (1, 6),
    "fade_in_ms": (0, 1000),
    "fade_out_ms": (0, 1000),
    "poll_interval_ms": (400, 5000),
    "left_width": (340, 900),
}


def app_dir() -> str:
    """程序所在目录：源码运行时是脚本目录，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _rename_legacy_logs(target: str) -> None:
    """把搬过来的旧日志文件改成新名字，免得目录里留着 wechat-toast.log 让人困惑。"""
    for suffix in ("", ".1", ".2"):
        old = os.path.join(target, f"wechat-toast.log{suffix}")
        new = os.path.join(target, f"desktop-toast.log{suffix}")
        if os.path.exists(old) and not os.path.exists(new):
            try:
                os.replace(old, new)
            except Exception:
                pass


def _migrate_legacy_dir(root: str, target: str) -> None:
    """把改名前的配置目录（%APPDATA%\\WeChatToast）整目录搬到新目录。"""
    legacy = os.path.join(root, LEGACY_APP_NAME)
    if os.path.isdir(target) or not os.path.isdir(legacy):
        return
    try:
        shutil.move(legacy, target)
    except Exception:
        # 旧程序可能还开着，日志文件被占用，退一步只搬配置
        try:
            os.makedirs(target, exist_ok=True)
            src = os.path.join(legacy, "config.json")
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(target, "config.json"))
        except Exception:
            pass
    _rename_legacy_logs(target)


def config_dir() -> str:
    """配置目录。

    打包后固定放到 %APPDATA%\\DesktopToast，这样 exe 被移动、复制、重新下载都不会丢配置；
    源码运行时直接用项目目录，方便开发调试。
    """
    if getattr(sys, "frozen", False):
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(root, APP_NAME)
        _migrate_legacy_dir(root, d)
    else:
        d = app_dir()
    os.makedirs(d, exist_ok=True)
    return d


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def default_avatar_dir() -> str:
    """默认头像目录：跟着配置目录走，不跟 exe 位置绑死。"""
    return os.path.join(config_dir(), "avatars")


def _migrate_exe_config() -> None:
    """旧版把 config.json 放在 exe 同目录，这里迁移到配置目录，避免用户配置丢失。"""
    if not getattr(sys, "frozen", False):
        return

    old = os.path.join(app_dir(), "config.json")
    new = config_path()
    if os.path.exists(old) and not os.path.exists(new):
        try:
            shutil.copy2(old, new)
            print(f"[info] 已迁移旧配置: {old} -> {new}")
        except Exception as e:
            print(f"[warn] 配置迁移失败: {e}")


def _normalize_apps(raw) -> list[dict]:
    """把「监听哪些应用」清洗成 [{key, name, aumid, match}]。

    match 全是小写，空项丢弃；整项没有有效匹配串的直接忽略，
    否则会出现「勾了但永远匹配不到」的幽灵条目。
    aumid 是精确匹配用的原始标识，有就带上，匹配时优先级最高。
    """
    if not isinstance(raw, list):
        return default_apps()

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        match = item.get("match")
        if not isinstance(match, list):
            match = [match] if match else []

        pats: list[str] = []
        for m in [name, *match]:
            s = str(m or "").strip().lower()
            if s and s not in pats:
                pats.append(s)
        aumid = str(item.get("aumid") or "").strip()
        if aumid and aumid.lower() not in pats:
            pats.append(aumid.lower())
        if not pats:
            continue

        key = str(item.get("key") or pats[0]).strip() or pats[0]

        # 老版本预置过「微信」条目。PC 微信不发通知、系统通知列表里也没有它，
        # 留着就是勾了也收不到的幽灵项，直接丢弃（带 aumid 的保留，那是真应用）
        if not aumid and key.lower() in GHOST_APP_KEYS:
            continue

        entry = {"key": key, "name": name, "match": pats}
        if aumid:
            entry["aumid"] = aumid
        out.append(entry)

    # 老配置里只剩废弃条目时回落到默认，免得升级后一条通知都收不到
    if raw and not out:
        return default_apps()

    return out


def _normalize_app_names(raw) -> dict[str, str]:
    """清洗 AUMID -> 中文名 学习缓存，只保留非空字符串。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        k = str(k or "").strip()
        v = str(v or "").strip()
        if k and v:
            out[k] = v
    return out


def normalize(cfg: dict) -> dict:
    """补齐缺失项并把数值夹到合法区间。"""
    out = dict(DEFAULT_CONFIG)
    out.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})

    for key, (lo, hi) in RANGES.items():
        try:
            val = out[key]
            val = float(val) if isinstance(DEFAULT_CONFIG[key], float) else int(val)
        except (TypeError, ValueError):
            val = DEFAULT_CONFIG[key]
        out[key] = min(hi, max(lo, val))

    if out["theme"] not in ("dark", "light"):
        out["theme"] = "dark"
    if out["position"] not in ("top-right", "top-left", "bottom-right", "bottom-left"):
        out["position"] = "top-right"
    if out["screen"] not in ("cursor", "primary"):
        out["screen"] = "cursor"

    # 免打扰列表：只保留非空字符串并去重（保持用户输入顺序）
    raw_ignore = out.get("ignore_sources")
    if not isinstance(raw_ignore, list):
        raw_ignore = []
    cleaned: list[str] = []
    for item in raw_ignore:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in cleaned:
            cleaned.append(name)
    out["ignore_sources"] = cleaned

    out["autostart"] = bool(out.get("autostart", False))
    out["merge_same_source"] = bool(out.get("merge_same_source", True))
    out["show_content"] = bool(out.get("show_content", True))

    # 监听范围：至少保留用户明确选择的集合，空列表表示「什么都不弹」
    out["enabled_apps"] = _normalize_apps(out.get("enabled_apps"))
    out["app_names"] = _normalize_app_names(out.get("app_names"))

    # 头像目录留空时落到配置目录下的 avatars
    av = out.get("avatar_dir") or ""
    # 旧版把默认头像目录记成了 exe 同目录的绝对路径，迁移后要重新指向新配置目录
    if av and os.path.normcase(os.path.normpath(av)) == os.path.normcase(
        os.path.normpath(os.path.join(app_dir(), "avatars"))
    ) and os.path.normcase(os.path.normpath(av)) != os.path.normcase(
        os.path.normpath(default_avatar_dir())
    ):
        av = ""
    out["avatar_dir"] = av or default_avatar_dir()

    return out


def _for_file(cfg: dict) -> dict:
    """落盘用的形态：默认头像目录不写死进文件，避免换机器/换路径后失效。"""
    out = dict(cfg)
    if os.path.normcase(os.path.normpath(out["avatar_dir"])) == os.path.normcase(
        os.path.normpath(default_avatar_dir())
    ):
        out["avatar_dir"] = ""
    return out


def load() -> dict:
    _migrate_exe_config()
    path = config_path()
    if not os.path.exists(path):
        cfg = normalize(dict(DEFAULT_CONFIG))
        _write(_for_file(cfg))
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[warn] 配置读取失败，使用默认值: {e}")
        return normalize(dict(DEFAULT_CONFIG))

    cfg = normalize(raw)
    # 文件内容与规范化结果不一致时（缺字段、越界、旧路径）顺手修好，避免用户手动改
    if _for_file(cfg) != raw:
        _write(_for_file(cfg))
    return cfg


def _write(data: dict) -> bool:
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[error] 配置保存失败: {e}")
        return False


def save(cfg: dict) -> bool:
    return _write(_for_file(normalize(cfg)))
