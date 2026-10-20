# -*- coding: utf-8 -*-
"""配置的默认值、读取、保存与范围校验。"""
from __future__ import annotations

import json
import os
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


def base_dir() -> str:
    """源码运行取脚本目录，打包后取 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(base_dir(), "config.json")


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

    return out


def load() -> dict:
    path = config_path()
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize(json.load(f))
    except Exception as e:
        print(f"[warn] 配置读取失败，使用默认值: {e}")
        return dict(DEFAULT_CONFIG)


def save(cfg: dict) -> bool:
    cfg = normalize(cfg)
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[error] 配置保存失败: {e}")
        return False
