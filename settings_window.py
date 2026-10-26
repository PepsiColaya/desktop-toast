# -*- coding: utf-8 -*-
"""可视化设置面板：左侧调参，右侧实时预览。"""
from __future__ import annotations

import copy
import os
import time
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import apps
import autostart
import config as cfgmod
import guide
import logo
import wechat
from logger import get
from toast import THEMES, Toast
from watcher import WeChatMessage

PREVIEW_MSGS = [
    WeChatMessage("示例群", "张三", "这个版本的接口文档我下午更新一下，你们先按旧的对", time.time(), 1),
    WeChatMessage("李四", "", "好的，收到，我这边先联调", time.time(), 2),
]

STYLE = """
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #22222A; }
/* 提示框双保险：QToolTip 规则管标签自身（含边距），
   富文本 div 管文字块，见 tooltip_html() 的说明 */
QToolTip {
    background-color: #FFFFFF; color: #22222A;
    border: 1px solid #DDDDE0; padding: 6px;
}
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
QLabel#warn { color: #C8730A; font-size: 12px; }
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
QScrollArea { border: none; }
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
/* 色值输入框：等宽字体，一眼能看出 #1F1F23 有没有打错 */
QLineEdit#hex {
    padding: 3px 4px; font-family: "Consolas", "Microsoft YaHei UI"; font-size: 12px;
}
QListWidget {
    border: 1px solid #E4E4EC; border-radius: 8px;
    background: #FCFCFD; padding: 3px; outline: 0;
}
QListWidget::item {
    min-height: 24px; padding-left: 6px; border-radius: 5px; color: #22222A;
}
QListWidget::item:hover { background: #F2FBF6; }
QListWidget::item:selected { background: #E8F8EF; color: #07A050; }
/* 监听应用是树：手机连接下面挂着它转发的手机 App */
QTreeWidget {
    border: 1px solid #E4E4EC; border-radius: 8px;
    background: #FCFCFD; padding: 3px; outline: 0;
}
QTreeWidget::item { min-height: 24px; border-radius: 5px; color: #22222A; }
/* 父项没勾时子项会被 disable，这里给个浅灰，别让它们看着还能点 */
QTreeWidget::item:disabled { color: #B4B4BE; }
QTreeWidget::item:hover { background: #F2FBF6; }
QTreeWidget::item:selected { background: #E8F8EF; color: #07A050; }
QTreeWidget::branch { background: transparent; }
QPushButton#mini { padding: 5px 12px; font-size: 12px; }
QPushButton[mini="true"] { padding: 5px 12px; font-size: 12px; }
/* 中间分割线：平时是浅灰细线，悬停变绿提示可以抓；
   宽度 3px 是抓取热区，太细会很难对准 */
QSplitter::handle:horizontal {
    background-color: #DCDCE6; width: 3px;
}
QSplitter::handle:horizontal:hover { background-color: #07C160; }
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

#: 提示框的固定配色，和面板保持一致
TOOLTIP_BG = "#FFFFFF"
TOOLTIP_FG = "#22222A"


def tooltip_html(*lines: str) -> str:
    """把提示文字包成带底色的富文本。

    提示框的最终配色由两处共同保证，缺一不可：

    1. STYLE 里的 ``QToolTip`` 规则——管提示标签本体，
       包括标签自带的几像素内容边距（早期只有富文本时，
       边距位置会露出被染黑的调色板，表现为「两边有黑框」）。
    2. 这里的富文本 ``<div>``——管文字块本身。
       QTipLabel 的调色板会被所在控件污染（左栏曾经因为
       ``background: transparent`` 把 Window/Base 全染成黑色），
       一旦 QSS 的 background 在某处失效，div 自带的白底
       还能兜住文字，不至于整块变黑。

    用 <div> 而不是 <span>，因为只有块级元素才会铺出背景块。
    """
    from html import escape

    body = "<br>".join(escape(l) for l in lines if l)
    if not body:
        return ""
    return (
        f'<div style="background-color:{TOOLTIP_BG};color:{TOOLTIP_FG};">'
        f"{body}</div>"
    )


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


def contrast_ratio(c1: str, c2: str) -> float:
    """两个颜色的 WCAG 对比度，1.0（完全一样）到 21.0（黑白）。"""
    def lum(hex_color: str) -> float:
        c = QColor(hex_color)

        def ch(v: int) -> float:
            v = v / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())

    a, b = lum(c1), lum(c2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class ColorRow(QWidget):
    """一行颜色配置：标题 + 色值输入 + 色块。

    色值可以直接粘贴（``#1F1F23`` / ``1F1F23`` / ``#fff`` 都认），
    也可以点右侧色块调系统调色板。两种入口都走同一套校验，
    输错就还原成上一个有效值，不会把坏色值存进配置。
    """

    changed = Signal(str)

    def __init__(self, title: str, value: str):
        super().__init__()
        self._value = cfgmod.normalize_hex_color(value, "#000000")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(8)

        self.lb_title = QLabel(title)
        lay.addWidget(self.lb_title)
        lay.addStretch(1)

        self.ed_hex = QLineEdit()
        self.ed_hex.setObjectName("hex")
        self.ed_hex.setFixedWidth(94)
        self.ed_hex.setMaxLength(7)
        self.ed_hex.setAlignment(Qt.AlignCenter)
        self.ed_hex.setToolTip(tooltip_html("直接输入色值", "支持 #1F1F23、1F1F23、#fff 三种写法"))
        self.ed_hex.editingFinished.connect(self._on_hex_edited)

        self.btn_swatch = QPushButton()
        self.btn_swatch.setObjectName("swatch")
        self.btn_swatch.setFixedSize(46, 24)
        self.btn_swatch.setToolTip(tooltip_html("点这里打开调色板"))
        self.btn_swatch.clicked.connect(self._pick)

        lay.addWidget(self.ed_hex)
        lay.addWidget(self.btn_swatch)

        self._sync()

    def _sync(self):
        self.ed_hex.setText(self._value)
        # 色块边界要跟着底色走：浅色块用灰边、深色块用深边，否则在白面板上看不出边界
        border = "#C8C8D2" if QColor(self._value).lightness() > 160 else "#3A3A44"
        self.btn_swatch.setStyleSheet(
            f'QPushButton#swatch {{ background: {self._value};'
            f' border: 1px solid {border}; border-radius: 6px; padding: 0; }}'
            f'QPushButton#swatch:hover {{ border-color: #07C160; }}'
        )

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._value), self, "选择颜色")
        if not c.isValid():
            return
        if c.name().upper() == self._value:
            return
        self.set_value(c.name())
        self.changed.emit(self._value)

    def _on_hex_edited(self):
        val = cfgmod.normalize_hex_color(self.ed_hex.text(), "")
        if not val:                        # 输错了就还原，别留半截色值
            self.ed_hex.setText(self._value)
            return
        if val == self._value:
            self.ed_hex.setText(val)       # 顺手把 "fff" 规范成 "#FFFFFF"
            return
        self.set_value(val)
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        self._value = cfgmod.normalize_hex_color(v, self._value)
        self._sync()


class PreviewPane(QWidget):
    """预览画布。"""

    resized = Signal()

    def __init__(self):
        super().__init__()
        self._pix: Optional[QPixmap] = None
        # 最小值别太大：用户把左栏拖宽后，右侧至少还要留这么大看预览
        self.setMinimumSize(340, 420)

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
        self.setMinimumSize(900, 560)
        self.resize(1080, 950)
        self.setStyleSheet(STYLE)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        # 切到「自定义」时用来起手的预置配色（dark / light）
        self._last_preset = "dark"

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

        # ---- 左右分栏：中间分割线可拖动，左栏宽度记入配置 ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setChildrenCollapsible(False)   # 不许把一侧拖到消失
        self.splitter = splitter
        splitter.splitterMoved.connect(self._on_splitter_moved)

        # ---- 左：参数区 ----
        # 注意：这里不能给 left_inner 设 background: transparent。
        # Qt 的 QSS 一旦在祖先上设透明背景，会把子孙控件的调色板
        # Window / Base / Button 全染成黑色，悬浮提示框继承后整块变黑，
        # 富文本只能盖住文字块，标签自带的 3px 左右边距还是会露黑边。
        # 不设背景时容器默认继承窗口的浅灰色底色，视觉效果一样。
        left_inner = QWidget()
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
        scroll.setMinimumWidth(340)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 允许纵向无限压缩，否则内容高度会把底部按钮挤出窗口
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        scroll.setMinimumHeight(180)
        self.scroll = scroll
        splitter.addWidget(scroll)

        # ---- 右：预览区 ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        cap = QLabel("实时预览")
        cap.setObjectName("hint")
        rv.addWidget(cap)
        self.preview = PreviewPane()
        self.preview.resized.connect(lambda: self._preview_timer.start(60))
        rv.addWidget(self.preview, 1)
        splitter.addWidget(right)

        # 默认左栏宽一点；窗口变大时多出的宽度只加给预览，左栏保持用户拖好的宽度
        splitter.setSizes([int(self._cfg.get("left_width", 540)), 10 ** 6])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        body.addWidget(splitter, 1)

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

        self._apply_cursors()

    def _apply_cursors(self):
        """所有能点的东西都换成手型光标。

        QSS 里没有 cursor 属性，只能逐个控件设；列表类只设在 viewport 上，
        免得滚动条和空白区也变成手型。
        """
        for cls in (QPushButton, QCheckBox, QComboBox):
            for w in self.findChildren(cls):
                w.setCursor(Qt.PointingHandCursor)
        for view in (getattr(self, "tree_apps", None), getattr(self, "lst_ignore", None)):
            if view is not None:
                view.viewport().setCursor(Qt.PointingHandCursor)

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
        self.cb_theme.addItem("自定义", "custom")
        style_combo(self.cb_theme)
        self.cb_theme.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self.cb_theme)
        lay.addLayout(row)

        # 自定义配色：只在选「自定义」时展开，选深/浅色时整块收起
        self.color_box = QWidget()
        cl = QVBoxLayout(self.color_box)
        cl.setContentsMargins(2, 4, 0, 6)
        cl.setSpacing(2)

        self.cr_bg = ColorRow("背景色", cfgmod.DEFAULT_CONFIG["custom_bg"])
        self.cr_title = ColorRow("标题文字", cfgmod.DEFAULT_CONFIG["custom_title"])
        self.cr_body = ColorRow("正文文字", cfgmod.DEFAULT_CONFIG["custom_body"])
        self.cr_border = ColorRow("边框", cfgmod.DEFAULT_CONFIG["custom_border"])
        for r in (self.cr_bg, self.cr_title, self.cr_body, self.cr_border):
            r.changed.connect(self._on_widget_change)
            cl.addWidget(r)

        # 白底白字这种搭配调完才发现「字没了」，这里提前提一句
        self.lb_contrast = QLabel("")
        self.lb_contrast.setObjectName("warn")
        self.lb_contrast.setWordWrap(True)
        cl.addWidget(self.lb_contrast)

        lay.addWidget(self.color_box)

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
        btn.setToolTip(tooltip_html("重新读取本机通知设置里的应用名单"))
        btn.clicked.connect(self._on_refresh_apps)
        head.addWidget(btn)
        lay.addLayout(head)

        self.tree_apps = QTreeWidget()
        self.tree_apps.setHeaderHidden(True)
        self.tree_apps.setColumnCount(1)
        self.tree_apps.setRootIsDecorated(True)
        self.tree_apps.setIndentation(16)
        self.tree_apps.setExpandsOnDoubleClick(False)
        self.tree_apps.setFixedHeight(200)
        self.tree_apps.itemChanged.connect(self._on_app_item_changed)
        lay.addWidget(self.tree_apps)

        # 手动添加手机 App：注册表没收录的（企业自建应用）才拦得住，
        # 加进来之后它才会出现在「手机连接」的子项里，取消勾选即可屏蔽。
        # 聊天应用（QQ / 微信）不用加——它们转发来的通知首行是联系人名，
        # 压根没有 App 名，拦不住也不该拦（见 watcher._phone_app_allowed）。
        row = QHBoxLayout()
        row.setSpacing(6)
        self.ed_phone_add = QLineEdit()
        self.ed_phone_add.setPlaceholderText("手动添加手机 App 名（仅注册表没收录的才需要）")
        self.ed_phone_add.setClearButtonEnabled(True)
        self.ed_phone_add.returnPressed.connect(self._add_phone_app)
        row.addWidget(self.ed_phone_add, 1)
        btn_add = QPushButton("添加")
        btn_add.setProperty("mini", True)     # QSS 属性选择器，objectName 留给测试定位
        btn_add.setObjectName("phone-add")    # 和免打扰那组重名，靠 objectName 区分
        btn_add.setToolTip(tooltip_html(
            "把手机 App 名加进「手机连接」的子项",
            "只有注册表里没收录的 App 才需要手动加",
            "加完之后在列表里取消勾选即可屏蔽它",
        ))
        btn_add.clicked.connect(self._add_phone_app)
        row.addWidget(btn_add)
        btn_del = QPushButton("移除选中")
        btn_del.setProperty("mini", True)
        btn_del.setObjectName("phone-del")
        btn_del.setToolTip(tooltip_html("从名单里移除手动添加的手机 App"))
        btn_del.clicked.connect(self._remove_phone_app)
        row.addWidget(btn_del)
        lay.addLayout(row)

        self.lb_apps_hint = QLabel()
        self.lb_apps_hint.setObjectName("hint")
        self.lb_apps_hint.setWordWrap(True)
        lay.addWidget(self.lb_apps_hint)

        return box

    def _flash_saved(self, text: str, ms: int = 1800):
        """在底栏闪一句提示。同样的文案已经显示着就不重复计时。"""
        if self.lb_saved.text() == text:
            return
        self.lb_saved.setText(text)
        QTimer.singleShot(
            ms, lambda: self.lb_saved.setText("") if self.lb_saved.text() == text else None
        )

    def _on_refresh_apps(self):
        """「刷新」按钮：重读注册表，并告诉用户读到了几个。

        只重建列表的话，点下去界面上什么反馈都没有，看着像没反应。
        """
        self._reload_apps()
        n = self.tree_apps.topLevelItemCount()
        self._flash_saved(f"已刷新：{n} 个应用" if n else "已刷新：没读到应用")

    def _phone_labels(self) -> list[tuple[str, str]]:
        """「手机连接」下面要列的手机 App：注册表那份 + 用户手动添加的。

        注册表会漏——有的 App 是企业自建应用，压根没注册进来，通知首行
        出现的名字在名单里找不到。这种可以在列表下方的输入框手动添加，
        加进来才能取消勾选屏蔽它。
        """
        rows = list(apps.phone_link_apps())
        seen = {label for label, _ in rows}
        for name in (self._cfg.get("phone_known") or []):
            if name not in seen:
                rows.append((name, ""))
                seen.add(name)
        rows.sort(key=lambda r: (r[0].lower(), r[1]))
        return rows

    def _add_phone_app(self):
        """把手动输入的手机 App 名加进 phone_known，重建子项列表。"""
        name = self.ed_phone_add.text().strip()
        if not name:
            return
        known = list(self._cfg.get("phone_known") or [])
        if name in known:
            self._flash_saved(f"「{name}」已经在名单里")
            return
        known.append(name)
        self._cfg["phone_known"] = known
        self.ed_phone_add.clear()
        self._reload_apps()
        self._flash_saved(f"已添加「{name}」，取消勾选即可屏蔽")

    def _remove_phone_app(self):
        """移除当前选中的手动添加子项（注册表里的不给移，移了也没意义）。"""
        item = self.tree_apps.currentItem()
        if item is None or item.parent() is None:
            self._flash_saved("请先选中「手机连接」下面要移除的子项")
            return
        name = str((item.data(0, Qt.UserRole) or {}).get("name") or "")
        known = list(self._cfg.get("phone_known") or [])
        if name not in known:
            self._flash_saved("这一项来自系统注册表，不能手动移除")
            return
        known.remove(name)
        self._cfg["phone_known"] = known
        self._reload_apps()
        self._flash_saved(f"已移除「{name}」")

    def _reload_apps(self):
        """列出本机通知设置里的应用，并标出哪些在监听名单里。

        数据源是注册表 Notifications\\Settings 下的 AUMID，
        也就是 Windows「设置 → 系统 → 通知」里出现过的应用。
        PC 微信不发通知，本来就不会出现在里面，正好排除掉。

        「手机连接」会折叠成一条，下面挂上它正在转发的手机 App。
        手机连接把所有手机通知都收进同一个 AUMID，只能靠通知首行的 App 名
        再筛一层，所以子项按名字存进 phone_apps（见 watcher._phone_app_allowed）。
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

        # 名单里有、但注册表里没出现的条目，只有「注册表压根读不到」时才补显示，
        # 否则会出现「微信」这种系统通知设置里根本没有的幽灵项。
        # 判据：registry_apps 为空 = 读取失败或系统真没通知过，此时不能清空用户名单。
        if not registry_apps:
            for i, item in enumerate(enabled):
                if i not in used:
                    rows.append((item, item["name"], "通知设置未读到", True))

        was_loading = self._loading
        self._loading = True
        self.tree_apps.clear()
        phone_labels = self._phone_labels()
        phone_picked = self._cfg.get("phone_apps")   # None = 不过滤，全收
        # 手机上的 App 可能和电脑上的应用同名（QQ 最典型），列表里会出现两行「QQ」，
        # 用户根本分不清取消的是哪个。同名时给子项加个后缀，但存进配置的仍是原名。
        top_names = {name for _, name, _, _ in rows}

        for record, name, sub, checked in rows:
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, record)
            it.setToolTip(0, tooltip_html(name, f"标识：{sub}"))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            self.tree_apps.addTopLevelItem(it)

            # 「手机连接」下面挂上它正在转发的手机 App，勾哪个收哪个
            if apps.is_phone_link_aumid(str(record.get("aumid") or sub)):
                for label, paumid in phone_labels:
                    shown = f"{label}（手机）" if label in top_names else label
                    ch = QTreeWidgetItem([shown])
                    ch.setData(0, Qt.UserRole, {"key": f"phone:{label}", "name": label})
                    ch.setToolTip(0, tooltip_html(
                        shown,
                        "来自「手机连接」转发",
                        f"标识：{paumid or '（手动添加，注册表里没有）'}",
                    ))
                    ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                    on = phone_picked is None or label in phone_picked
                    ch.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                    it.addChild(ch)
                it.setExpanded(True)
        self._loading = was_loading

        self._sync_phone_children()
        self._update_apps_hint()

    def _on_app_item_changed(self, item, _column: int = 0):
        """勾选变化：父项（手机连接）带着子项一起启用/置灰。"""
        if self._loading:
            return
        if item.parent() is None and item.childCount():
            self._sync_phone_children()
        self._on_widget_change()

    def _sync_phone_children(self):
        """父项没勾时，子项置灰——保留勾选状态，重新勾上还能接着用。

        置灰靠 QSS 的 ``QTreeWidget::item:disabled``：item 的 color 在
        QSS 里被写死了，调色板改不动，只能靠 disable 触发的伪状态。
        """
        was = self._loading
        self._loading = True
        for i in range(self.tree_apps.topLevelItemCount()):
            top = self.tree_apps.topLevelItem(i)
            if not top.childCount():
                continue
            on = top.checkState(0) == Qt.Checked
            for j in range(top.childCount()):
                ch = top.child(j)
                flags = ch.flags()
                ch.setFlags(flags | Qt.ItemIsEnabled if on else flags & ~Qt.ItemIsEnabled)
        self._loading = was

    def _update_apps_hint(self):
        """列表下面挂一句针对性说明，告诉用户接下来该干什么。

        勾选状态会变，所以直接读列表控件，不依赖调用方传进来的快照。
        """
        pl = apps.phone_link_status()
        checked = [
            self.tree_apps.topLevelItem(i).data(0, Qt.UserRole) or {}
            for i in range(self.tree_apps.topLevelItemCount())
            if self.tree_apps.topLevelItem(i).checkState(0) == Qt.Checked
        ]

        def is_phone_entry(entry: dict) -> bool:
            # 列表里只会有系统通知设置里真实存在的应用，认「手机连接」看 aumid 就够
            return apps.is_phone_link_aumid(entry.get("aumid", ""))

        phone_on = any(is_phone_entry(e) for e in checked)

        if pl == "active" and phone_on:
            self.lb_apps_hint.setText(
                "已就绪：手机上的通知会经「手机连接」转发进来。"
                "展开「手机连接」还能只勾想收的手机 App。"
            )
        elif pl == "active":
            self.lb_apps_hint.setText(
                "检测到「手机连接」正在转发手机通知。"
                "想收到手机上的消息，请在上面的列表里勾选「手机连接」。"
            )
        elif pl == "installed":
            self.lb_apps_hint.setText(
                "检测到本机装了「手机连接」，但还没转发通知，"
                "需要先配对手机并打开通知转发（见下方教程）。"
            )
        elif pl == "none":
            self.lb_apps_hint.setText(
                "本机没有检测到「手机连接」。如果某个手机 App（比如微信）"
                "自己不往电脑端发通知，就得靠它把手机通知转过来，"
                "配置方法见下方教程。"
            )
        else:
            self.lb_apps_hint.setText("")

    def _build_phonelink(self) -> QGroupBox:
        """手机连接检测 + 配置教程入口。"""
        box = QGroupBox("手机连接（手机消息来源）")
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
        self.btn_phonelink_detect.clicked.connect(lambda: self._refresh_phonelink(reload_apps=True))
        row.addWidget(self.btn_phonelink_detect)

        self.btn_phonelink_guide = QPushButton("查看连接配置教程")
        self.btn_phonelink_guide.setObjectName("mini")
        self.btn_phonelink_guide.clicked.connect(self._open_phonelink_guide)
        row.addWidget(self.btn_phonelink_guide)
        row.addStretch(1)
        lay.addLayout(row)

        self._refresh_phonelink()
        return box

    def _refresh_phonelink(self, reload_apps: bool = False):
        if reload_apps:
            # 「重新检测」时把应用列表也重读一遍：刚配好手机的话，
            # 新的手机 App 要立刻出现在子项里，不然用户以为没生效
            self._reload_apps()
        status = apps.phone_link_status()
        if status == "none":
            self.lb_phonelink.setText(
                "未检测到「手机连接」。手机上的通知要先经它转发到电脑，本程序才读得到。"
                "PC 微信就是典型例子——它自己不往消息中心发通知。"
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
                "「手机连接」工作正常，手机上的 App 通知会转发到电脑。"
                "在上方「监听应用」里勾选手机连接即可弹卡片。" + tail
            )
            self.btn_phonelink_guide.setText("查看配置教程")

        if reload_apps:
            # 按钮点的才给反馈；构建界面和读配置时静默
            self._flash_saved({
                "none": "没检测到「手机连接」",
                "installed": "检测到了，但还没在转发通知",
            }.get(status, "「手机连接」工作正常"))

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
        self._flash_saved("教程已生成")
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

        self.chk_click = QCheckBox("点击卡片唤起来源应用")
        self.chk_click.setToolTip(tooltip_html(
            "电脑上的应用：把它的窗口拉到前台（没开就直接启动）",
            "手机连接转发来的：打开「手机连接」，来源 App 在手机上",
            "认不出来的应用：点了没反应，不会弹错误框",
        ))
        self.chk_click.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_click)

        self.chk_merge = QCheckBox("同一会话连续消息合并成一张卡片")
        self.chk_merge.stateChanged.connect(self._on_widget_change)
        lay.addWidget(self.chk_merge)

        self.chk_content = QCheckBox("卡片显示消息正文")
        self.chk_content.setToolTip(tooltip_html(
            "取消勾选后，卡片只显示会话名和「有一条新消息」，"
            "适合旁边有人时不想让内容被看到"
        ))
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
        self.ed_ignore.setToolTip(tooltip_html(
            "手机连接转发的微信消息：填手机微信里的群名或备注名",
            "其他应用：填通知的第一行标题",
        ))
        self.ed_ignore.returnPressed.connect(self._add_ignore)
        row.addWidget(self.ed_ignore, 1)

        btn_add = QPushButton("添加")
        btn_add.setProperty("mini", True)      # QSS 属性选择器，objectName 留给测试定位
        btn_add.setObjectName("ignore-add")    # 和手机 App 那组重名，靠 objectName 区分
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
        btn_del.setProperty("mini", True)
        btn_del.setObjectName("ignore-del")    # 同上，靠 objectName 区分
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
        if c["theme"] in ("dark", "light"):
            self._last_preset = c["theme"]
        self.cr_bg.set_value(c["custom_bg"])
        self.cr_title.set_value(c["custom_title"])
        self.cr_body.set_value(c["custom_body"])
        self.cr_border.set_value(c["custom_border"])
        self._sync_color_rows_visible()
        self._update_contrast_hint()
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
        self.chk_click.setChecked(bool(c["click_to_open_source"]))
        self.chk_merge.setChecked(bool(c["merge_same_source"]))
        self.chk_content.setChecked(bool(c["show_content"]))
        # 以注册表真实状态为准，避免配置与系统不一致时开关显示错误
        self.chk_autostart.setChecked(self._autostart_state)

        self.lst_ignore.clear()
        for name in c.get("ignore_sources", []):
            self.lst_ignore.addItem(QListWidgetItem(name))

        self._reload_apps()
        self._refresh_phonelink()

        # 中间分割线位置：左栏多宽由用户上次拖出来的位置决定
        if hasattr(self, "splitter"):
            self.splitter.setSizes([int(c.get("left_width", 540)), 10 ** 6])

        path = c.get("avatar_dir", "")
        fm = QFontMetrics(self.lb_avatar_dir.font())
        self.lb_avatar_dir.setText(fm.elidedText(path, Qt.ElideMiddle, 230))
        self.lb_avatar_dir.setToolTip(tooltip_html(path))

        cfgp = cfgmod.config_path()
        self.lb_cfg_path.setText("配置：" + fm.elidedText(cfgp, Qt.ElideMiddle, 240))
        self.lb_cfg_path.setToolTip(tooltip_html(f"配置自动保存在：{cfgp}"))

        self._loading = False

    def _collect(self):
        c = self._cfg
        c["theme"] = self.cb_theme.currentData()
        c["custom_bg"] = self.cr_bg.value()
        c["custom_title"] = self.cr_title.value()
        c["custom_body"] = self.cr_body.value()
        c["custom_border"] = self.cr_border.value()
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
        c["click_to_open_source"] = self.chk_click.isChecked()
        c["merge_same_source"] = self.chk_merge.isChecked()
        c["show_content"] = self.chk_content.isChecked()
        c["autostart"] = self.chk_autostart.isChecked()
        c["ignore_sources"] = [
            self.lst_ignore.item(i).text() for i in range(self.lst_ignore.count())
        ]
        enabled: list[dict] = []
        phone_picked = None          # 手机连接一个都没勾上时的兜底（保持原值）
        phone_seen = False
        for i in range(self.tree_apps.topLevelItemCount()):
            top = self.tree_apps.topLevelItem(i)
            if top.checkState(0) != Qt.Checked:
                continue
            record = top.data(0, Qt.UserRole)
            if record:
                enabled.append(record)
            if not apps.is_phone_link_aumid(str((record or {}).get("aumid", ""))):
                continue
            phone_seen = True
            total = top.childCount()
            picked = []
            for j in range(total):
                ch = top.child(j)
                if ch.checkState(0) != Qt.Checked:
                    continue
                # 显示名可能带了「（手机）」后缀，配置里存的必须是真实 App 名，
                # 否则过滤时对不上通知首行，勾了等于没勾
                meta = ch.data(0, Qt.UserRole) or {}
                picked.append(str(meta.get("name") or ch.text(0)))
            if total == 0:
                # 读不到手机 App 列表（注册表异常），别拿空名单把通知全挡掉
                picked = self._cfg.get("phone_apps")
            elif len(picked) == total:
                picked = None        # 全勾 = 不过滤，以后新装的手机 App 也自动收
            phone_picked = picked
        c["enabled_apps"] = enabled
        if phone_seen:
            c["phone_apps"] = phone_picked
        # 中间分割线位置，存的是左栏宽度
        if hasattr(self, "splitter"):
            c["left_width"] = self.splitter.sizes()[0]
        self._cfg = cfgmod.normalize(c)

    def _on_theme_changed(self, *_):
        """主题下拉框变了：展开/收起配色区，必要时用当前预置配色起手。"""
        if self._loading:
            return
        name = self.cb_theme.currentData()
        if name in ("dark", "light"):
            self._last_preset = name
        elif name == "custom":
            self._seed_custom_from_preset()
        self._sync_color_rows_visible()
        self._on_widget_change()

    def _sync_color_rows_visible(self):
        """只有选「自定义」时才显示那四行颜色。"""
        self.color_box.setVisible(self.cb_theme.currentData() == "custom")

    def _update_contrast_hint(self):
        """标题 / 正文和背景差得太少时提醒一句。

        白底白字调完才发现「字没了」，那时只会以为程序坏了。
        按 WCAG 的对比度算，2.5 以下基本就是看不清。
        """
        if self.cb_theme.currentData() != "custom":
            self.lb_contrast.setText("")
            self.lb_contrast.setVisible(False)
            return

        bg = self.cr_bg.value()
        weak = [name for name, c in
                (("标题", self.cr_title.value()), ("正文", self.cr_body.value()))
                if contrast_ratio(bg, c) < 2.5]
        if weak:
            self.lb_contrast.setText("、".join(weak) + "和背景颜色太接近，可能看不清")
            self.lb_contrast.setVisible(True)
        else:
            self.lb_contrast.setText("")
            self.lb_contrast.setVisible(False)

    def _seed_custom_from_preset(self):
        """切到「自定义」时，色值从用户刚才看到的那套配色起手。

        否则从浅色切过去会突然变成深色，第一眼像是主题丢了。
        只在四项都还是初始默认（深色）时才铺：用户已经调过就原样保留，
        免得来回切换把自己配好的颜色冲掉。
        """
        d = cfgmod.DEFAULT_CONFIG
        untouched = (
            self.cr_bg.value() == d["custom_bg"]
            and self.cr_title.value() == d["custom_title"]
            and self.cr_body.value() == d["custom_body"]
            and self.cr_border.value() == d["custom_border"]
        )
        if not untouched:
            return
        base = THEMES.get(self._last_preset, THEMES["dark"])
        self.cr_bg.set_value(base["bg"].name())
        self.cr_title.set_value(base["title"])
        self.cr_body.set_value(base["body"])
        self.cr_border.set_value(base["border"].name())

    def _on_widget_change(self, *_):
        if self._loading:
            return
        self._collect()
        self._update_apps_hint()
        self._update_contrast_hint()
        self._preview_timer.start(90)       # 防抖，拖动滑块时不至于卡
        self._autosave_timer.start(500)     # 停手半秒后自动落盘

    def _on_splitter_moved(self, *_):
        """拖动中间分割线：只记宽度和刷预览，不碰其它配置。"""
        if self._loading:
            return
        self._preview_timer.start(90)
        self._autosave_timer.start(500)

    def _reset(self):
        # 必须深拷贝：DEFAULT_CONFIG 里的列表/字典是模块级对象，
        # 浅拷贝后一旦被就地改动，后面所有「恢复默认」都会拿到被污染的值
        self._cfg = copy.deepcopy(dict(cfgmod.DEFAULT_CONFIG))
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

        # 小屏幕上把窗口压到可用区域内，内容区自带滚动条
        screen = QGuiApplication.primaryScreen().availableGeometry()
        max_h = screen.height() - 60
        if self.height() > max_h:
            self.resize(self.width(), max_h)
        max_w = screen.width() - 40
        if self.width() > max_w:
            self.resize(max_w, self.height())

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
