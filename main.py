# -*- coding: utf-8 -*-
"""DesktopToast —— 桌面通知悬浮提示，程序入口。

应用隐藏在后台时来了通知，屏幕角落浮出卡片显示「哪个应用 + 谁发的 + 说了什么」，
默认 3 秒淡出。支持可视化调参、系统托盘常驻。
"""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import apps
import autostart
import config as cfgmod
import logger
import logo
import wechat
from settings_window import SettingsWindow
from toast import Toast, ToastManager
from watcher import WeChatMessage, WeChatWatcher

APP_TITLE = "DesktopToast"
SERVER_NAME = "DesktopToast.SingleInstance"

log = logger.get("main")


def make_tray_icon() -> QIcon:
    return logo.logo_icon()


class Bridge(QObject):
    """把后台线程的消息安全地送回 UI 线程。"""
    message = Signal(object)
    denied = Signal()
    # 学到新的 AUMID -> 应用名，用于把设置界面里的英文名换成中文名
    app_learned = Signal(str, str)


def ensure_single_instance() -> bool:
    """已有实例在跑时，通知它打开设置窗口并返回 False。"""
    try:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: F401
    except Exception:
        return True

    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show-settings")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return False
    return True


def main() -> int:
    logger.setup()
    logger.install_excepthook()
    log.info("========== 启动 %s ==========", APP_TITLE)

    cfg = cfgmod.load()
    log.info("配置目录: %s", cfgmod.config_dir())

    app = QApplication(sys.argv)
    app.setApplicationName(cfgmod.APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if not ensure_single_instance():
        log.info("已有实例在运行，唤起它的设置窗口后退出")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("系统托盘不可用，无法常驻")
        QMessageBox.critical(None, APP_TITLE, "当前系统托盘不可用，程序无法运行。")
        return 1

    bridge = Bridge()
    state = {"paused": False}
    test_toasts: list[Toast] = []
    watcher: WeChatWatcher | None = None

    manager = ToastManager(cfg, app, on_open_wechat=wechat.open_wechat)
    settings = SettingsWindow(cfg)

    # ---------- 托盘 ----------
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip(f"{APP_TITLE} · 运行中")

    menu = QMenu()
    act_open = QAction("打开微信", menu)
    act_open.triggered.connect(wechat.open_wechat)
    menu.addAction(act_open)

    act_settings = QAction("设置…", menu)
    act_settings.triggered.connect(lambda: settings.show_window(cfgmod.load()))
    menu.addAction(act_settings)

    menu.addSeparator()

    act_pause = QAction("暂停监听", menu)
    menu.addAction(act_pause)

    act_log = QAction("查看日志", menu)
    menu.addAction(act_log)

    menu.addSeparator()
    act_quit = QAction("退出", menu)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.show()

    # ---------- 事件 ----------
    def toggle_pause():
        state["paused"] = not state["paused"]
        act_pause.setText("继续监听" if state["paused"] else "暂停监听")
        tray.setToolTip(f"{APP_TITLE} · {'已暂停' if state['paused'] else '运行中'}")
        tray.showMessage(
            APP_TITLE,
            "已暂停，不再弹出新消息卡片" if state["paused"] else "已恢复监听",
            QSystemTrayIcon.Information, 1500,
        )
        log.info("监听%s", "已暂停" if state["paused"] else "已恢复")

    act_pause.triggered.connect(toggle_pause)

    def open_log():
        path = logger.log_path()
        try:
            os.startfile(os.path.dirname(path))
        except Exception as e:
            log.warning("打开日志目录失败: %s", e)

    act_log.triggered.connect(open_log)

    def quit_app():
        log.info("用户请求退出")
        if watcher is not None:
            watcher.stop()
        manager.close_all()
        app.quit()

    act_quit.triggered.connect(quit_app)

    # 单击打开微信、双击打开设置：单击延迟一点，避免双击时先被当成单击
    click_timer = QTimer()
    click_timer.setSingleShot(True)
    click_timer.setInterval(230)
    click_timer.timeout.connect(wechat.open_wechat)

    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.Trigger:          # 单击
            click_timer.start()
        elif reason == QSystemTrayIcon.DoubleClick:    # 双击
            click_timer.stop()
            settings.show_window(cfgmod.load())

    tray.activated.connect(on_tray_activated)

    # ---------- 配置应用 ----------
    def apply_cfg(new_cfg: dict):
        # 应用名学习缓存是运行时攒的，设置面板那份配置可能是旧的，别被覆盖掉
        merged = dict(new_cfg)
        merged["app_names"] = {**(new_cfg.get("app_names") or {}), **(cfg.get("app_names") or {})}
        cfg.clear()
        cfg.update(merged)
        manager.cfg = cfg
        # 轮询间隔、免打扰名单改完立即生效，不必重启
        if watcher is not None:
            watcher.set_poll_interval(cfg.get("poll_interval_ms", 1000) / 1000.0)
            watcher.set_ignore_sources(cfg.get("ignore_sources", []))
            watcher.set_enabled_apps(cfg.get("enabled_apps", []))
            # 手机连接的子项：勾了哪些手机 App 才提醒
            watcher.set_phone_apps(
                cfg.get("phone_apps"),
                [label for label, _ in apps.phone_link_apps()],
            )

    settings.applied.connect(apply_cfg)

    def show_test(test_cfg: dict):
        msg = WeChatMessage(
            "产品研发群", "张伟",
            "这是一条测试消息，看看现在的效果是否合适", time.time(), 0,
        )
        t = Toast(msg, test_cfg, on_open_wechat=wechat.open_wechat)
        t.closed.connect(lambda x: test_toasts.remove(x) if x in test_toasts else None)
        test_toasts.append(t)
        t.appear()

    settings.test_requested.connect(show_test)

    # ---------- 消息监听 ----------
    def on_denied():
        QMessageBox.warning(
            settings, "无法读取系统通知",
            "需要允许本程序访问系统通知。\n\n"
            "请打开：设置 → 隐私和安全性 → 通知 → 允许应用访问通知。\n\n"
            "微信用户请注意：PC 微信自己不往消息中心发通知，"
            "消息要经「手机连接」转发，配置方法见设置面板里的「手机连接」一栏。",
        )

    bridge.message.connect(lambda m: None if state["paused"] else manager.push(m))
    bridge.denied.connect(on_denied)

    def on_status(status: str):
        log.info("监听状态: %s", status)
        if status == "access_denied":
            bridge.denied.emit()

    # ---------- 应用名学习 ----------
    # 通知里的 app_info.display_name 是系统本地化过的名字，比注册表里的英文标识友好。
    # 学到就存进配置，下次打开设置界面直接显示中文名。
    _learn_save_timer = QTimer()
    _learn_save_timer.setSingleShot(True)
    _learn_save_timer.setInterval(2000)

    def on_app_learned(aumid: str, name: str):
        if not aumid or not name:
            return
        known = cfg.get("app_names", {}) or {}
        if known.get(aumid) == name:
            return
        known = dict(known)
        known[aumid] = name
        cfg["app_names"] = known
        log.info("学到应用中文名: %s -> %s", aumid, name)
        # 防抖：开机时通知中心一堆历史通知会连着学，攒一批再写盘
        _learn_save_timer.start()

    def flush_learned():
        if not _learn_save_timer.isActive():
            return
        _learn_save_timer.stop()
        if cfgmod.save(cfg):
            log.info("应用名缓存已保存，共 %d 条", len(cfg.get("app_names", {})))

    _learn_save_timer.timeout.connect(flush_learned)
    bridge.app_learned.connect(on_app_learned)

    watcher = WeChatWatcher(
        on_message=bridge.message.emit,
        on_status=on_status,
        poll_interval=cfg.get("poll_interval_ms", 1000) / 1000.0,
        ignore_sources=cfg.get("ignore_sources", []),
        enabled_apps=cfg.get("enabled_apps", []),
        on_app_learned=bridge.app_learned.emit,
        phone_apps=cfg.get("phone_apps"),
        phone_known=[label for label, _ in apps.phone_link_apps()],
    )
    watcher.start()

    # ---------- 单实例服务端 ----------
    server = None
    try:
        from PySide6.QtNetwork import QLocalServer

        QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer(app)
        server.listen(SERVER_NAME)

        def on_new_connection():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnected.connect(conn.deleteLater)
            settings.show_window(cfgmod.load())

        server.newConnection.connect(on_new_connection)
    except Exception as e:
        log.warning("单实例服务启动失败: %s", e)

    # 改名迁移：旧版注册的是 WeChatToast，路径指向旧 exe。
    # 只靠下面的 is_enabled() 判断会以为「自启已开」，结果开机起来的还是旧程序。
    if autostart.has_legacy():
        if cfg.get("autostart"):
            autostart.migrate_legacy()
            log.info("开机自启项已从 WeChatToast 迁移到 DesktopToast")
        else:
            autostart.set_enabled(False)
            log.info("已清理改名前的旧开机自启项")
    # 配置里开了自启但注册表项丢了（重装、清理工具）时补一次
    elif cfg.get("autostart") and not autostart.is_enabled():
        log.info("检测到开机自启已失效，正在重建")
        autostart.set_enabled(True)

    log.info("%s已启动。右键托盘图标可进入设置或退出。", APP_TITLE)
    code = app.exec()
    if watcher is not None:
        watcher.stop()
    if server is not None:
        server.close()
    log.info("已退出，code=%s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
