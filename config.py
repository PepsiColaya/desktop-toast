# -*- coding: utf-8 -*-
"""配置的默认值、读取、保存与范围校验。"""
from __future__ import annotations

import json
import os
import shutil
import sys

APP_NAME = "WeChatToast"

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
    # ---- 行为 ----
    "duration_ms": 3000,             # 停留时长
    "max_visible": 3,                # 同屏最多几张
    "fade_in_ms": 170,
    "fade_out_ms": 280,
    "hover_pause": True,             # 鼠标悬停时暂停倒计时
    "click_to_open_wechat": True,
    "poll_interval_ms": 1000,        # 通知轮询间隔
    "ignore_sources": [],            # 不提醒的会话名
    "avatar_dir": "",                # 头像目录，留空则用程序目录下的 avatars
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
}


def app_dir() -> str:
    """程序所在目录：源码运行时是脚本目录，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_dir() -> str:
    """配置目录。

    打包后固定放到 %APPDATA%\\WeChatToast，这样 exe 被移动、复制、重新下载都不会丢配置；
    源码运行时直接用项目目录，方便开发调试。
    """
    if getattr(sys, "frozen", False):
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(root, "WeChatToast")
    else:
        d = app_dir()
    os.makedirs(d, exist_ok=True)
    return d


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def default_avatar_dir() -> str:
    """默认头像目录：跟着配置目录走，不跟 exe 位置绑死。"""
    return os.path.join(config_dir(), "avatars")


def _migrate_legacy() -> None:
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
    if not isinstance(out["ignore_sources"], list):
        out["ignore_sources"] = []

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
    _migrate_legacy()
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
