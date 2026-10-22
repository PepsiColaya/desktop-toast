# -*- coding: utf-8 -*-
"""统一日志：同时写控制台和配置文件目录下的日志文件。

打包成 --noconsole 的 exe 后没有控制台，出问题时用户什么也看不到。
这里把日志落到 `%APPDATA%\\WeChatToast\\wechat-toast.log`（滚动保留 2 份），
用户只要把文件发过来就能定位问题。
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_ROOT = "wechattoast"
_ready = False


def log_path() -> str:
    # 延迟导入，避免 config <-> logger 循环依赖
    import config as cfgmod

    return os.path.join(cfgmod.config_dir(), "wechat-toast.log")


def setup(level: int = logging.INFO) -> logging.Logger:
    """初始化根 logger，重复调用无副作用。"""
    global _ready

    root = logging.getLogger(_ROOT)
    if _ready:
        return root

    root.setLevel(logging.DEBUG)
    root.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    try:
        fh = RotatingFileHandler(
            log_path(), maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        # 目录不可写时降级为仅控制台，不影响主功能
        pass

    # pythonw / --noconsole 下 stderr 可能是 None
    if sys.stderr is not None:
        try:
            sh = logging.StreamHandler(sys.stderr)
            sh.setLevel(level)
            sh.setFormatter(fmt)
            root.addHandler(sh)
        except Exception:
            pass

    _ready = True
    return root


def get(name: str = "") -> logging.Logger:
    setup()
    return logging.getLogger(f"{_ROOT}.{name}" if name else _ROOT)


def install_excepthook() -> None:
    """把未捕获异常写进日志，避免程序静默退出后无从排查。"""
    logger = get("crash")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("未捕获异常", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook

    # 线程里抛出的异常默认只打到 stderr，这里一并收进日志
    def thread_hook(args):
        logger.error(
            "线程 %s 未捕获异常", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    try:
        import threading

        threading.excepthook = thread_hook
    except Exception:
        pass
