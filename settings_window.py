# -*- coding: utf-8 -*-
"""可视化设置面板：左侧调参，右侧实时预览。"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

import apps
import autostart
import config as cfgmod
import guide
import logo
import wechat
from logger import get
from toast import Toast
from watcher import WeChatMessage

PREVIEW_MSGS = [
    WeChatMessage("产品研发群", "张伟", "这个版本的接口文档我下午更新一下，你们先按旧的对", time.time(), 1),
    WeChatMessage("李静", "", "好的，收到，我这边先联调", time.time(), 2),
]

STYLE = """
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #22222A; }
QGroupBox {
    border: 1px solid #E4E4EC; border-radius: 10px;
    margin-top: 13px; padding: 12px 12px 8px 12px; background: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 14px; padding: 0 5px;
    color: #6B6B78; font-weight: 600; font-size: 12px;
}
QLabel#hint { color: #8A8A96; font-size: 12px; }
QLabel#value { color: #07A050; font-weight: 600; }
QSlider::groove:horizontal { height: 4px; background: #E8E8EE; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #07C160; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 15px; height: 15px; margin: -6px 0; border-radius: 8px;
    background: #FFFFFF; border: 2px solid #07C160;
}
QSlider::handle:horizontal:hover { background: #EAFBF1; }
QComboBox {
    border: 1px solid #DDDDE5; border-radius: 6px;
    padding: 5px 10px; background: #FFFFFF; min-width: 110px;
}
QComboBox:hover { border-color: #07C160; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #DDDDE5;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: #E8F8EF;
    selection-color: #07A050;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding-left: 8px;
    color: #22222A;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #F2FBF6;
    color: #07A050;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #CFCFD8; background: #FFFFFF;
}
QCheckBox::indicator:checked { background: #07C160; border-color: #07C160; }
QPushButton {
    padding: 7px 18px; border-radius: 7px;
    border: 1px solid #DDDDE5; background: #FFFFFF; color: #33333C;
}
QPushButton:hover { background: #F5F6F8; border-color: #C8C8D2; }
QPushButton#primary {
    background: #07C160; border: none; color: #FFFFFF; font-weight: 600;
}
QPushButton#primary:hover { background: #06AD56; }
QPushButton#ghost { border: none; background: transparent; color: #7A7A86; }
QPushButton#ghost:hover { color: #07A050; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #D6D6DE; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #BEBEC8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QFrame#sep { background: #ECECF2; border: none; max-height: 1px; }
QLineEdit {
    border: 1px solid #DDDDE5; border-radius: 6px;
    padding: 5px 9px; background: #FFFFFF; color: #22222A;
    selection-background-color: #07C160; selection-color: #FFFFFF;
}
QLineEdit:focus { border-color: #07C160; }
QListWidget {
    border: 1px solid #E4E4EC; border-radius: 8px;
    background: #FCFCFD; padding: 3px; outline: 0;
}
QListWidget::item {
    min-height: 24px; padding-left: 6px; border-radius: 5px; color: #22222A;
}
QListWidget::item:hover { background: #F2FBF6; }
QListWidget::item:selected { background: #E8F8EF; color: #07A050; }
QPushButton#mini { padding: 5px 12px; font-size: 12px; }
"""


POPUP_QSS = """
QListView {
    background-color: #FFFFFF;
    border: 1px solid #DDDDE5;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
}
QListView::item {
    min-height: 27px;
    padding-left: 8px;
    color: #22222A;
    border-radius: 5px;
}
QListView::item:hover { background-color: #F2FBF6; color: #07A050; }
QListView::item:selected { background-color: #E8F8EF; color: #07A050; }
"""


def style_combo(combo: QComboBox) -> None:
    """给下拉框换上自定义列表视图。

    Windows 原生风格的弹出列表不跟随 QSS，系统开深色主题时会变成黑底黑字，
    这里显式指定 QListView 并单独上样式。
    """
    view = QListView()
    view.setStyleSheet(POPUP_QSS)
    combo.setView(view)

    # 弹出层容器也要透明，否则圆角四角会露出底色
    popup = view.window()
    if popup is not None:
        popup.setAttribute(Qt.WA_TranslucentBackground, True)


class SliderRow(QWidget):
    """标题 + 数值 + 滑块。"""

    changed = Signal(int)

    def __init__(self, title: str, lo: int, hi: int, value: int,
                 fmt: Callable[[int], str]):
        super().__init__()
        self._fmt = fmt

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 3)
        lay.setSpacing(1)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.lb_title = QLabel(title)
        self.lb_value = QLabel(fmt(value))
        self.lb_value.setObjectName("value")
        head.addWidget(self.lb_title)
        head.addStretch(1)
        head.addWidget(self.lb_value)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)

        lay.addLayout(head)
        lay.addWidget(self.slider)

    def _on_change(self, v: int):
        self.lb_value.setText(self._fmt(v))
        self.changed.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int):
        self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self.lb_value.setText(self._fmt(int(v)))
        self.slider.blockSignals(False)


class PreviewPane(QWidget):
    """预览画布。"""

    resized = Signal()

    def __init__(self):
        super().__init__()
        self._pix: Optional[QPixmap] = None
        self.setMinimumSize(430, 480)

    def set_pixmap(self, pix: QPixmap):
        self._pix = pix
        self.update()

    def resizeEvent(self, evt):
        super().resizeEvent(evt)
        self.resized.emit()

    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect().adjusted(1, 1, -1, -1)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor("#F7F9FC"))
        grad.setColorAt(1, QColor("#E7ECF3"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 10, 10)
        p.fillPath(path, grad)
        p.strokePath(path, QColor("#E1E5EC"))

        if self._pix is None:
            return
        # pixmap 带 devicePixelRatio，宽度要换算回逻辑像素才能正确居中
        dpr = self._pix.devicePixelRatio() or 1.0
        pw = self._pix.width() / dpr
        ph = self._pix.height() / dpr
        x = int((self.width() - pw) / 2)
        y = int((self.height() - ph) / 2)
        p.drawPixmap(QPoint(max(0, x), max(0, y)), self._pix)


class SettingsWindow(QWidget):
    """配置窗口。保存后通过 applied 信号把新配置交回主程序。"""

    applied = Signal(dict)
    test_requested = Signal(dict)

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfgmod.normalize(dict(cfg))
        self._loading = False
        # 注册表里的真实状态，用于判断自启开关是否被改动过
        self._autostart_state = autostart.is_enabled()

        self.setWindowTitle("DesktopToast · 设置")
        self.setWindowIcon(logo.logo_icon())
        self.setMinimumSize(880, 560)
        self.resize(940, 950)
        self.setStyleSheet(STYLE)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        # 改动后自动落盘，不需要手动点保存
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave)

        self._build()
        self._load_from_cfg()
        self._refresh_preview()

    # ---------------- 构建界面 ----------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(16, 8, 16, 0)
        body.setSpacing(16)

        # ---- 左：参数区 ----
        left_inner = QWidget()
        left_inner.setStyleSheet("background: transparent;")
        lv = QVBoxLayout(left_inner)
        lv.setContentsMargins(0, 0, 8, 0)
        lv.setSpacing(4)

        lv.addWidget(self._build_appearance())
        lv.addWidget(self._build_apps())
        lv.addWidget(self._build_phonelink())
        lv.addWidget(self._build_position())
        lv.addWidget(self._build_behavior())
        lv.addWidget(self._build_ignore())
        lv.addWidget(self._build_avatar())
        lv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left_inner)
        scroll.setFixedWidth(452)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 允许纵向无限压缩，否则内容高度会把底部按钮挤出窗口
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        scroll.setMinimumHeight(180)
        self.scroll = scroll
        body.addWidget(scroll)

        # ---- 右：预览区 ----
        right = QVBoxLayout()
        right.setSpacing(8)
        cap = QLabel("实时预览")
        cap.setObjectName("hint")
        right.addWidget(cap)
        self.preview = PreviewPane()
        self.preview.resized.connect(lambda: self._preview_timer.start(60))
        right.addWidget(self.preview, 1)
        body.addLayout(right, 1)

        root.addLayout(body, 1)

        # ---- 底部按钮 ----
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        bar = QHBoxLayout()
        bar.setContentsMargins(20, 12, 20, 16)

        btn_reset = QPushButton("恢复默认")
        btn_reset.setObjectName("ghost")
        btn_reset.clicked.connect(self._reset)

        btn_test = QPushButton("在桌面试一下")
        btn_test.clicked.connect(lambda: self.test_requested.emit(dict(self._cfg)))

        self.lb_saved = QLabel("")
        self.lb_saved.setObjectName("hint")

        # 配置落地位置放在底栏，用户随时能看到，又不占左栏高度
        self.lb_cfg_path = QLabel()
        self.lb_cfg_path.setObjectName("hint")
        self.lb_cfg_path.setTextInteractionFlags(Qt.TextSelectableByMouse)

        btn_close = QPushButton("完成")
        btn_close.setObjectName("primary")
        btn_close.clicked.connect(self.hide)

        bar.addWidget(btn_reset)
        bar.addWidget(btn_test)
        bar.addWidget(self.lb_saved)
        bar.addStretch(1)
        bar.addWidget(self.lb_cfg_path)
        bar.addSpacing(10)
        bar.addWidget(btn_close)
        root.addLayout(bar)

    def _build_appearance(self) -> QGroupBox:
        box = QGroupBox("外观")
        lay = QVBoxLayout(box)
        lay.setSpacing(2)

        row = QHBoxLayout()
        row.addWidget(QLabel("主题"))
        row.addStretch(1)
        self.cb_theme = QComboBox()
        self.cb_theme.addItem("深色", "dark")
        self.cb_theme.addItem("浅色", "light")
        style_combo(self.cb_theme)
        self.cb_theme.currentIndexChanged.connect(self._on_widget_change)
        row.addWidget(self.cb_theme)
        lay.addLayout(row)

        self.sl_width = SliderRow("卡片宽度", 240, 560, 340, lambda v: f"{v} px")
        self.sl_scale = SliderRow("整体缩放", 80, 150, 100, lambda v: f"{v}%")
        self.sl_radius = SliderRow("圆角", 0, 24, 14, lambda v: f"{v} px")
        self.sl_shadow = SliderRow("阴影扩散", 0, 30, 16, lambda v: f"{v} px")
        self.sl_opacity = SliderRow("不透明度", 40, 100, 96, lambda v: f"{v}%")
        self.sl_gap = SliderRow("卡片间距", 0, 24, 8, lambda v: f"{v} px")

        for w in (self.sl_width, self.sl_scale, self.sl_radius,
                  self.sl_shadow, self.sl_opacity, self.sl_gap):
            w.changed.connect(self._on_widget_change)
            lay.addWidget(w)

        return box

    def _build_apps(self) -> QGroupBox:
        box = QGroupBox("监听应用")
        lay = QVBoxLayout(box)
        lay.setSpacing(5)

        head = QHBoxLayout()
        hint = QLabel("来自「设置 → 系统 → 通知」里真正发过通知的应用；一个都不勾就什么都不弹。")
        hint.setObjectName("hint")
        head.addWidget(hint, 1)
        btn = QPushButton("刷新")
        btn.setObjectName("mini")
        btn.setToolTip("重新读取本机通知设置里的应用名单")
        btn.clicked.connect(self._reload_apps)
        head.addWidget(btn)
        lay.addLayout(head)

        self.lst_apps = QListWidget()
        self.lst_apps.setFixedHeight(118)
        self.lst_apps.itemChanged.connect(self._on_widget_change)
        lay.addWidget(self.lst_apps)

        self.lb_apps_hint = QLabel()
        self.lb_apps_hint.setObjectName("hint")
        self.lb_apps_hint.setWordWrap(True)
        lay.addWidget(self.lb_apps_hint)

        return box

    def _reload_apps(self):
        """列出本机通知设置里的应用，并标出哪些在监听名单里。

        数据源是注册表 Notifications\\Settings 下的 AUMID，
        也就是 Windows「设置 → 系统 → 通知」里出现过的应用。
        PC 微信不发通知，本来就不会出现在里面，正好排除掉。
        """
        enabled = list(self._cfg.get("enabled_apps", []))
        learned = self._cfg.get("app_names", {}) or {}
        registry_apps = apps.list_notification_apps()

        used: set[int] = set()
        rows: list[tuple[dict, str, str, bool]] = []

        for aumid in registry_apps:
            name = apps.resolve_name(aumid, learned)
            hay = f"{aumid} {name}".lower()
            hit = None
            for i, item in enumerate(enabled):
                if i in used:
                    continue
                if any(p in hay for p in item.get("match", [])):
                    hit = item
                    used.add(i)
                    break
            record = hit or {
                "key": aumid,
                "name": name,
                "aumid": aumid,
                "match": apps.match_patterns(name, aumid),
            }
            # 已经学到的中文名覆盖掉列表里的显示
            record["name"] = name
            rows.append((record, name, aumid, hit is not None))

        # 名单里有、但注册表里还没出现的（比如微信走手机连接转发）也要显示，否则会被误清掉
        phone_labels = [l for l, _ in apps.phone_link_apps()]
        for i, item in enumerate(enabled):
            if i not in used:
                # 这一项匹配到了手机连接转发的某个 App，说明它是经手机连接进来的
                via_phone = any(
                    p and p in " ".join(phone_labels).lower()
                    for p in item.get("match", [])
                )
                sub = "经「手机连接」转发" if via_phone else "未出现在通知设置里"
                rows.append((item, item["name"], sub, True))

        was_loading = self._loading
        self._loading = True
        self.lst_apps.clear()
        for record, name, sub, checked in rows:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, record)
            it.setToolTip(
                f"{name}\n标识：{sub}\n匹配关键字：{', '.join(record.get('match', []))}"
            )
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.lst_apps.addItem(it)
        self._loading = was_loading

        self._update_apps_hint()

    def _update_apps_hint(self):
        """列表下面挂一句针对性说明，告诉用户接下来该干什么。

        勾选状态会变，所以直接读列表控件，不依赖调用方传进来的快照。
        """
        pl = apps.phone_link_status()
        checked = [
            self.lst_apps.item(i).data(Qt.UserRole) or {}
            for i in range(self.lst_apps.count())
            if self.lst_apps.item(i).checkState() == Qt.Checked
        ]
        phone_labels = " ".join(l for l, _ in apps.phone_link_apps()).lower()

        def covers_wechat(entry: dict) -> bool:
            # 直接勾了手机连接，或者勾的项能匹配到「微信」这个手机 App
            if apps.is_phone_link_aumid(entry.get("aumid", "")):
                return True
            return any(
                p and (p == "微信" or (phone_labels and p in phone_labels))
                for p in entry.get("match", [])
            )

        wechat_on = any(covers_wechat(e) for e in checked)

        if pl == "active" and wechat_on:
            self.lb_apps_hint.setText(
                "已就绪：微信等手机 App 的消息会经「手机连接」转发进来。"
                "还没见到中文名的应用，等它发过一条通知就会自动补上。"
            )
        elif pl == "active":
            self.lb_apps_hint.setText(
                "检测到「手机连接」正在转发手机通知。"
                "想收到微信消息，请勾选「手机连接」或勾选「微信」这一项。"
            )
        elif pl == "installed":
            self.lb_apps_hint.setText(
                "检测到本机装了「手机连接」，但还没转发通知，"
                "需要先配对手机并打开通知转发（见下方教程）。"
            )
        elif pl == "none":
            self.lb_apps_hint.setText(
                "本机没有检测到「手机连接」。PC 微信自己不发通知，"
                "想收到微信消息需要先按下方教程配置手机连接。"
            )
        else:
            self.lb_apps_hint.setText("")

    def _build_phonelink(self) -> QGroupBox:
        """手机连接检测 + 配置教程入口。"""
        box = QGroupBox("手机连接（微信消息来源）")
        lay = QVBoxLayout(box)
        lay.setSpacing(7)

        self.lb_phonelink = QLabel()
        self.lb_phonelink.setObjectName("hint")
        self.lb_phonelink.setWordWrap(True)
        lay.addWidget(self.lb_phonelink)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_phonelink_detect = QPushButton("重新检测")
        self.btn_phonelink_detect.setObjectName("mini")
        self.btn_phonelink_detect.clicked.connect(self._refresh_phonelink)
        row.addWidget(self.btn_phonelink_detect)

        self.btn_phonelink_guide = QPushButton("查看连接配置教程")
        self.btn_phonelink_guide.setObjectName("mini")
        self.btn_phonelink_guide.clicked.connect(self._open_phonelink_guide)
        row.addWidget(self.btn_phonelink_guide)
        row.addStretch(1)
        lay.addLayout(row)

        self._refresh_phonelink()
        return box

    def _refresh_phonelink(self):
        status = apps.phone_link_status()
        if status == "none":
            self.lb_phonelink.setText(
                "未检测到「手机连接」。PC 微信自己不往消息中心发通知，"
                "需要先在电脑上安装并配对手机连接，微信消息才进得来。"
            )
            self.btn_phonelink_guide.setText("查看安装配对教程")
        elif status == "installed":
            self.lb_phonelink.setText(
                "已检测到「手机连接」，但还没有在转发通知。"
                "请配对手机并打开「通知」转发开关，教程里有逐步说明。"
            )
            self.btn_phonelink_guide.setText("查看配置教程")
        else:
            phones = apps.phone_link_apps()
            tail = ""
            if phones:
                names = "、".join(l for l, _ in phones)
                if len(names) > 60:
                    names = names[:60].rstrip("、") + "…"
                tail = f"\n正在转发 {len(phones)} 个手机 App：{names}"
            self.lb_phonelink.setText(
                "「手机连接」工作正常，手机上的微信等 App 通知会转发到电脑。"
                "在上方「监听应用」里勾选手机连接即可弹卡片。" + tail
            )
            self.btn_phonelink_guide.setText("查看配置教程")

    def _open_phonelink_guide(self):
        """生成本地 HTML 教程并用默认浏览器打开。"""
        status = apps.phone_link_status()
        if not guide.open_guide(status):
            QMessageBox.warning(
                self, "打不开教程",
                "教程文件生成失败，请检查配置目录是否有写入权限。",
            )
            return
        path = guide.guide_path()
        self.lb_saved.setText("教程已生成")
        QTimer.singleShot(1800, lambda: self.lb_saved.setText(""))
        log = get("settings")
        log.info("已生成手机连接教程: %s", path)

    def _build_position(self) -> QGroupBox:
        box = QGroupBox("位置")
        lay = QVBoxLayout(box)
        lay.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("显示位置"))
        self.cb_pos = QComboBox()
        for text, val in (("右上角", "top-right"), ("左上角", "top-left"),
                          ("右下角", "bottom-right"), ("左下角", "bottom-left")):
            self.cb_pos.addItem(text, val)
        style_combo(self.cb_pos)
        self.cb_pos.currentIndexChanged.connect(self._on_widget_change)
        row.addWidget(self.cb_pos)

        row.addSpacing(6)
        row.addWidget(QLabel("屏幕"))
        self.cb_screen = QComboBox()
        self.cb_screen.addItem("跟随鼠标", "cursor")
        self.cb_screen.addItem("主屏", "primary")
        style_combo(self.cb_screen)
        self.cb_screen.currentIndexChanged.connect(self._on_widget_change)
        row.addWidget(self.cb_screen)
        row.addStretch(1)
        lay.addLayout(row)

        self.sl_margin = SliderRow("距屏幕边缘", 6, 120, 22, lambda v: f"{v} px")
        self.sl_margin.changed.connect(self._on_widget_change)
        lay.addWidget(self.sl_margin)

        return box

    def _build_behavior(self) -> QGroupBox:
        box = QGroupBox("行为")
        lay = QVBoxLayout(box)
        lay.setSpacing(2)

        self.sl_duration = SliderRow("停留时长", 800, 20000, 3000, lambda v: f"{v/1000:.1f} 秒")
        self.sl_duration.changed.connect(self._on_widget_change)
        lay.addWidget(self.sl_duration)

        self.sl_max = SliderRow("同屏最多", 1, 6, 3, lambda v: f"{v} 张")
        self.sl_max.changed.connect(self._on_widget_change)
        lay.addWidget(self.sl_max)

        self.chk_hover = QCheckBox("鼠标悬停时暂停倒计时")
        self.chk_hover.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_hover)

        self.chk_click = QCheckBox("点击卡片打开微信")
        self.chk_click.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_click)

        self.chk_merge = QCheckBox("同一会话连续消息合并成一张卡片")
        self.chk_merge.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_merge)

        self.chk_content = QCheckBox("卡片显示消息正文")
        self.chk_content.setToolTip(
            "取消勾选后，卡片只显示会话名和「有一条新消息」，"
            "适合旁边有人时不想让内容被看到"
        )
        self.chk_content.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_content)

        self.chk_autostart = QCheckBox("开机自动启动")
        self.chk_autostart.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_autostart)

        return box

    def _build_ignore(self) -> QGroupBox:
        box = QGroupBox("免打扰")
        lay = QVBoxLayout(box)
        lay.setSpacing(5)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.ed_ignore = QLineEdit()
        self.ed_ignore.setPlaceholderText("填会话名后回车，该会话来消息不再弹卡片")
        self.ed_ignore.setToolTip(
            "手机连接转发的微信消息：填手机微信里的群名或备注名\n"
            "其他应用：填通知的第一行标题"
        )
        self.ed_ignore.returnPressed.connect(self._add_ignore)
        row.addWidget(self.ed_ignore, 1)

        btn_add = QPushButton("添加")
        btn_add.setObjectName("mini")
        btn_add.clicked.connect(self._add_ignore)
        row.addWidget(btn_add)
        lay.addLayout(row)

        note = QLabel(
            "填什么：经「手机连接」转发的消息，填<b>手机微信里的群名或备注名</b>；"
            "其他应用填通知的第一行标题。必须和卡片标题一模一样，"
            "可以先不填，等卡片弹出来照着抄。"
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.lst_ignore = QListWidget()
        self.lst_ignore.setFixedHeight(60)
        self.lst_ignore.setSelectionMode(QListWidget.ExtendedSelection)
        row2.addWidget(self.lst_ignore, 1)

        col = QVBoxLayout()
        col.setSpacing(4)
        btn_del = QPushButton("移除选中")
        btn_del.setObjectName("mini")
        btn_del.clicked.connect(self._remove_ignore)
        col.addWidget(btn_del)
        col.addStretch(1)
        row2.addLayout(col)
        lay.addLayout(row2)

        return box

    def _add_ignore(self):
        name = self.ed_ignore.text().strip()
        if not name:
            return
        existing = [self.lst_ignore.item(i).text() for i in range(self.lst_ignore.count())]
        if name not in existing:
            self.lst_ignore.addItem(QListWidgetItem(name))
            self._on_widget_change()
        self.ed_ignore.clear()

    def _remove_ignore(self):
        for item in self.lst_ignore.selectedItems():
            self.lst_ignore.takeItem(self.lst_ignore.row(item))
        self._on_widget_change()

    def _build_avatar(self) -> QGroupBox:
        box = QGroupBox("头像")
        lay = QVBoxLayout(box)
        lay.setSpacing(6)

        hint = QLabel(
            "卡片左上角默认显示会话名首字的渐变色方块。"
            "想让某个会话显示真实头像：把图片裁剪成正方形（建议 200×200 以上），"
            "命名为「会话名.png」或「会话名.jpg」放进下面的目录即可。"
            "文件名要和卡片标题里的名字完全一致，包括空格和表情符号。"
            "修改或新增图片后不用重启，下一张卡片自动生效。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lb_avatar_dir = QLabel()
        self.lb_avatar_dir.setObjectName("hint")
        self.lb_avatar_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.lb_avatar_dir, 1)

        btn = QPushButton("打开目录")
        btn.clicked.connect(self._open_avatar_dir)
        row.addWidget(btn)
        lay.addLayout(row)

        return box

    def _open_avatar_dir(self):
        d = self._cfg.get("avatar_dir") or ""
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            QMessageBox.warning(self, "打不开目录", f"{d}\n\n{e}")

    # ---------------- 读写配置 ----------------
    def _load_from_cfg(self):
        self._loading = True
        c = self._cfg

        idx = self.cb_theme.findData(c["theme"])
        self.cb_theme.setCurrentIndex(max(0, idx))
        idx = self.cb_pos.findData(c["position"])
        self.cb_pos.setCurrentIndex(max(0, idx))
        idx = self.cb_screen.findData(c["screen"])
        self.cb_screen.setCurrentIndex(max(0, idx))

        self.sl_width.set_value(c["card_width"])
        self.sl_scale.set_value(round(c["scale"] * 100))
        self.sl_radius.set_value(c["radius"])
        self.sl_shadow.set_value(c["shadow"])
        self.sl_opacity.set_value(round(c["opacity"] * 100))
        self.sl_gap.set_value(c["gap"])
        self.sl_margin.set_value(c["margin"])
        self.sl_duration.set_value(c["duration_ms"])
        self.sl_max.set_value(c["max_visible"])

        self.chk_hover.setChecked(bool(c["hover_pause"]))
        self.chk_click.setChecked(bool(c["click_to_open_wechat"]))
        self.chk_merge.setChecked(bool(c["merge_same_source"]))
        self.chk_content.setChecked(bool(c["show_content"]))
        # 以注册表真实状态为准，避免配置与系统不一致时开关显示错误
        self.chk_autostart.setChecked(self._autostart_state)

        self.lst_ignore.clear()
        for name in c.get("ignore_sources", []):
            self.lst_ignore.addItem(QListWidgetItem(name))

        self._reload_apps()
        self._refresh_phonelink()

        path = c.get("avatar_dir", "")
        fm = QFontMetrics(self.lb_avatar_dir.font())
        self.lb_avatar_dir.setText(fm.elidedText(path, Qt.ElideMiddle, 230))
        self.lb_avatar_dir.setToolTip(path)

        cfgp = cfgmod.config_path()
        self.lb_cfg_path.setText("配置：" + fm.elidedText(cfgp, Qt.ElideMiddle, 240))
        self.lb_cfg_path.setToolTip("配置自动保存在：\n" + cfgp)

        self._loading = False

    def _collect(self):
        c = self._cfg
        c["theme"] = self.cb_theme.currentData()
        c["position"] = self.cb_pos.currentData()
        c["screen"] = self.cb_screen.currentData()
        c["card_width"] = self.sl_width.value()
        c["scale"] = round(self.sl_scale.value() / 100, 2)
        c["radius"] = self.sl_radius.value()
        c["shadow"] = self.sl_shadow.value()
        c["opacity"] = round(self.sl_opacity.value() / 100, 2)
        c["gap"] = self.sl_gap.value()
        c["margin"] = self.sl_margin.value()
        c["duration_ms"] = self.sl_duration.value()
        c["max_visible"] = self.sl_max.value()
        c["hover_pause"] = self.chk_hover.isChecked()
        c["click_to_open_wechat"] = self.chk_click.isChecked()
        c["merge_same_source"] = self.chk_merge.isChecked()
        c["show_content"] = self.chk_content.isChecked()
        c["autostart"] = self.chk_autostart.isChecked()
        c["ignore_sources"] = [
            self.lst_ignore.item(i).text() for i in range(self.lst_ignore.count())
        ]
        c["enabled_apps"] = [
            self.lst_apps.item(i).data(Qt.UserRole)
            for i in range(self.lst_apps.count())
            if self.lst_apps.item(i).checkState() == Qt.Checked
        ]
        self._cfg = cfgmod.normalize(c)

    def _on_widget_change(self, *_):
        if self._loading:
            return
        self._collect()
        self._update_apps_hint()
        self._preview_timer.start(90)       # 防抖，拖动滑块时不至于卡
        self._autosave_timer.start(500)     # 停手半秒后自动落盘

    def _reset(self):
        self._cfg = dict(cfgmod.DEFAULT_CONFIG)
        self._load_from_cfg()
        self._refresh_preview()
        self._autosave()

    def _autosave(self):
        """把当前控件值写入配置文件并即时应用到运行中的程序。"""
        self._collect()
        ok = cfgmod.save(self._cfg)

        # 只有用户真的动了开关才去改注册表，避免每次自动保存都写一遍
        want = bool(self._cfg.get("autostart"))
        if want != self._autostart_state:
            if autostart.set_enabled(want):
                self._autostart_state = want
            else:
                ok = False
                self._cfg["autostart"] = self._autostart_state
                cfgmod.save(self._cfg)
                self._loading = True
                self.chk_autostart.setChecked(self._autostart_state)
                self._loading = False
                self.lb_saved.setText("开机自启设置失败，请检查权限")

        if ok:
            self.applied.emit(dict(self._cfg))
            self.lb_saved.setText("已自动保存")
            QTimer.singleShot(1800, lambda: self.lb_saved.setText(""))
        elif "开机自启" not in self.lb_saved.text():
            self.lb_saved.setText("保存失败，请检查目录权限")

    def hideEvent(self, evt):
        super().hideEvent(evt)
        # 关窗口时兜底保存一次，防止防抖计时器还没触发
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._autosave()

    def show_window(self, cfg: Optional[dict] = None):
        # 每次打开都重新读一次注册表，外部改动过也能显示正确状态
        self._autostart_state = autostart.is_enabled()
        if cfg is not None:
            self._cfg = cfgmod.normalize(dict(cfg))
            self._load_from_cfg()

        # 小屏幕上把窗口压到可用高度内，内容区自带滚动条
        screen = QGuiApplication.primaryScreen().availableGeometry()
        max_h = screen.height() - 60
        if self.height() > max_h:
            self.resize(self.width(), max_h)

        self._refresh_preview()
        self.show()
        self.raise_()
        self.activateWindow()
        # 列表控件拿到焦点会把面板滚到中间，这里回到顶部，保证每次打开都从头看
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(0))
        # 从托盘/单实例唤起时本进程在后台，Windows 会拦住抢焦点。
        # show() 之后窗口还没映射，必须等事件循环跑过一轮再置前，否则会被系统拒绝。
        QTimer.singleShot(0, self._raise_to_front)
        QTimer.singleShot(180, self._raise_to_front)

    def _raise_to_front(self):
        if not self.isVisible():
            return
        try:
            self.raise_()
            self.activateWindow()
            wechat.force_foreground(int(self.winId()))
        except Exception as e:
            get("settings").debug("置前失败: %s", e)

    # ---------------- 预览渲染 ----------------
    def _refresh_preview(self):
        c = self._cfg
        gap = c["gap"]

        toasts: list[Toast] = []
        for msg in PREVIEW_MSGS:
            t = Toast(msg, c)
            t.setAttribute(Qt.WA_DontShowOnScreen, True)
            t.show()
            toasts.append(t)

        total_h = sum(t.card_h for t in toasts) + gap * (len(toasts) - 1)
        total_w = max(t.card_w for t in toasts)
        s_max = max(t.shadow for t in toasts)

        # 带阴影的画布
        canvas_w = total_w + s_max * 2
        canvas_h = total_h + s_max * 2 + 6 * (len(toasts) - 1)

        dpr = 2.0
        pix = QPixmap(int(canvas_w * dpr), int(canvas_h * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(float(c["opacity"]))

        y = 0
        for t in toasts:
            shot = QPixmap(int(t.width() * dpr), int(t.height() * dpr))
            shot.setDevicePixelRatio(dpr)
            shot.fill(Qt.transparent)
            t.render(shot)
            p.drawPixmap(QPoint(0, int(y)), shot)
            y += t.card_h + gap
        p.end()

        for t in toasts:
            t.close()
            t.deleteLater()

        # 缩放到预览区
        avail_w = max(120, self.preview.width() - 48)
        avail_h = max(120, self.preview.height() - 48)
        k = min(1.0, avail_w / canvas_w, avail_h / canvas_h)
        if k < 1.0:
            pix = pix.scaled(
                int(canvas_w * k), int(canvas_h * k),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )

        self.preview.set_pixmap(pix)

    def resizeEvent(self, evt):
        super().resizeEvent(evt)
        if self.isVisible():
            self._preview_timer.start(120)
