# -*- coding: utf-8 -*-
"""微信消息悬浮卡片（Qt 绘制：圆角、阴影、淡入淡出、多条堆叠）。"""
from __future__ import annotations

from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath,
    QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget

from watcher import WeChatMessage

THEMES = {
    "dark": {
        "bg": QColor("#1F1F23"),
        "border": QColor("#34343C"),
        "title": "#FFFFFF",
        "body": "#B4B4BE",
    },
    "light": {
        "bg": QColor("#FFFFFF"),
        "border": QColor("#E3E3EA"),
        "title": "#17171C",
        "body": "#5B5B66",
    },
}

AVATAR_COLORS = ["#5B8DEF", "#E8743B", "#2FB38A", "#9B6BD6",
                 "#D9614C", "#3C9BD1", "#C79A2E", "#6E7BD9"]


def avatar_color(name: str) -> str:
    if not name:
        return AVATAR_COLORS[0]
    return AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]


def wrap_text(text: str, fm: QFontMetrics, max_width: int, max_lines: int = 2) -> list[str]:
    """按像素宽度折行，超出 max_lines 时最后一行加省略号。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ["（新消息）"]

    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                break
            continue
        if cur and fm.horizontalAdvance(cur + ch) > max_width:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
        else:
            cur += ch
    if len(lines) < max_lines:
        lines.append(cur)

    consumed = sum(len(x) for x in lines)
    if consumed < len(text.replace("\n", "")):
        tail = lines[-1]
        while tail and fm.horizontalAdvance(tail + "…") > max_width:
            tail = tail[:-1]
        lines[-1] = tail + "…"

    return [x for x in lines if x != ""] or [""]


class Toast(QWidget):
    """单条消息的悬浮卡片。所有尺寸由 config 推导，便于实时调参。"""

    closed = Signal(object)

    def __init__(self, msg: WeChatMessage, cfg: dict,
                 on_open_wechat: Optional[Callable[[], None]] = None):
        super().__init__(None)
        self.msg = msg
        self.cfg = cfg
        self.on_open_wechat = on_open_wechat or (lambda: None)
        self.theme = THEMES.get(cfg.get("theme", "dark"), THEMES["dark"])

        self._hovering = False
        self._closing = False
        self._anims: list = []

        # ---- 由配置推导尺寸 ----
        k = float(cfg.get("scale", 1.0))
        self.card_w = int(cfg.get("card_width", 340))
        self.shadow = int(cfg.get("shadow", 16))
        self.radius = int(cfg.get("radius", 14))
        self.pad = max(6, round(14 * k))
        self.avatar = max(20, round(38 * k))
        self.title_size = max(9, round(14 * k))
        self.body_size = max(8, round(13 * k))
        self.line_h = max(13, round(19 * k))
        self.title_h = max(15, round(20 * k))
        self.title_gap = max(3, round(7 * k))
        self.text_gap = max(6, round(12 * k))

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        # ---- 字体 ----
        family = cfg.get("font_family", "Microsoft YaHei UI")
        self.f_title = QFont(family)
        self.f_title.setPixelSize(self.title_size)
        self.f_title.setWeight(QFont.DemiBold)

        self.f_body = QFont(family)
        self.f_body.setPixelSize(self.body_size)

        self.f_avatar = QFont(family)
        self.f_avatar.setPixelSize(max(10, round(self.avatar * 0.42)))
        self.f_avatar.setWeight(QFont.Bold)

        # ---- 排版 ----
        text_x = self.pad + self.avatar + self.text_gap
        text_w = self.card_w - text_x - self.pad

        fm_title = QFontMetrics(self.f_title)
        fm_body = QFontMetrics(self.f_body)

        self.title_text = fm_title.elidedText(msg.display_title, Qt.ElideRight, max(20, text_w))
        self.body_lines = wrap_text(msg.content, fm_body, max(20, text_w), max_lines=2)

        self.card_h = self.pad * 2 + self.title_h + self.title_gap + len(self.body_lines) * self.line_h
        self.card_h = max(self.card_h, self.pad * 2 + self.avatar)

        self.resize(self.card_w + self.shadow * 2, self.card_h + self.shadow * 2)

        # ---- 文字控件（绝对定位，坐标需加阴影留白）----
        s = self.shadow
        self.lb_title = QLabel(self)
        self.lb_title.setText(self.title_text)
        self.lb_title.setFont(self.f_title)
        self.lb_title.setStyleSheet(f"color: {self.theme['title']}; background: transparent;")
        self.lb_title.setGeometry(s + text_x, s + self.pad, text_w, self.title_h)

        self.lb_body = QLabel(self)
        self.lb_body.setText("\n".join(self.body_lines))
        self.lb_body.setFont(self.f_body)
        self.lb_body.setStyleSheet(f"color: {self.theme['body']}; background: transparent;")
        self.lb_body.setGeometry(
            s + text_x, s + self.pad + self.title_h + self.title_gap,
            text_w, len(self.body_lines) * self.line_h,
        )

        for lb in (self.lb_title, self.lb_body):
            lb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lb.setContentsMargins(0, 0, 0, 0)
            lb.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        # ---- 动画 ----
        self.setWindowOpacity(0.0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)

    @property
    def bg_opacity(self) -> float:
        """背景不透明度：悬停时补满，保证文字始终清晰。"""
        if self._hovering:
            return 1.0
        return float(self.cfg.get("opacity", 0.96))

    # ---------- 绘制 ----------
    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        s = self.shadow
        rect = QRectF(s, s, self.card_w, self.card_h)

        # 柔和投影：多层圆角矩形叠加
        if s > 0:
            for i in range(s, 0, -1):
                alpha = max(0, int(70 * (1 - i / s) ** 2))
                if alpha <= 0:
                    continue
                path = QPainterPath()
                path.addRoundedRect(
                    rect.adjusted(-i * 0.6, -i * 0.6 + 3, i * 0.6, i * 0.6 + 3),
                    self.radius + i * 0.5, self.radius + i * 0.5,
                )
                p.fillPath(path, QColor(0, 0, 0, alpha))

        # 卡片主体：只让背景半透明，文字保持不透明
        bg = QColor(self.theme["bg"])
        bg.setAlphaF(max(0.0, min(1.0, self.bg_opacity)))
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        p.fillPath(path, bg)
        p.strokePath(path, QPen(self.theme["border"], 1))

        # 头像
        d = self.avatar
        ax = s + self.pad
        ay = s + (self.card_h - d) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(avatar_color(self.msg.source)))
        p.drawEllipse(QRectF(ax, ay, d, d))

        p.setPen(QColor("#FFFFFF"))
        p.setFont(self.f_avatar)
        initial = (self.msg.source or "?")[0]
        p.drawText(QRectF(ax, ay - 1, d, d), Qt.AlignCenter, initial)

    # ---------- 交互 ----------
    def enterEvent(self, _evt):
        self._hovering = True
        if self.cfg.get("hover_pause", True):
            self._timer.stop()
        self.update()                     # 背景补满不透明，方便看清

    def leaveEvent(self, _evt):
        self._hovering = False
        if self.cfg.get("hover_pause", True):
            self._restart_timer()
        self.update()

    def mousePressEvent(self, evt):
        if evt.button() == Qt.LeftButton:
            if self.cfg.get("click_to_open_wechat", True):
                self.on_open_wechat()
            self.fade_out()
        elif evt.button() == Qt.RightButton:
            self._show_menu(evt.globalPosition().toPoint())

    def _show_menu(self, pos: QPoint):
        m = QMenu(self)
        act_open = QAction("打开微信", self)
        act_open.triggered.connect(self.on_open_wechat)
        m.addAction(act_open)
        m.addSeparator()
        act_close = QAction("关闭此提示", self)
        act_close.triggered.connect(self.fade_out)
        m.addAction(act_close)
        m.exec(pos)

    # ---------- 动画 ----------
    def appear(self):
        self.show()
        self.raise_()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(int(self.cfg.get("fade_in_ms", 170)))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anims.append(anim)
        self._restart_timer()

    def _restart_timer(self):
        if self._closing:
            return
        self._timer.start(int(self.cfg.get("duration_ms", 3000)))

    def fade_out(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()

        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(int(self.cfg.get("fade_out_ms", 280)))
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._finish)
        anim.start()
        self._anims.append(anim)

    def _finish(self):
        self.closed.emit(self)
        self.close()
        self.deleteLater()


class ToastManager(QObject):
    """负责排队、堆叠与位置计算。"""

    def __init__(self, cfg: dict, app: QApplication,
                 on_open_wechat: Optional[Callable[[], None]] = None):
        super().__init__()
        self.cfg = cfg
        self.app = app
        self.on_open_wechat = on_open_wechat or (lambda: None)

        self.active: list[Toast] = []
        self.pending: deque[WeChatMessage] = deque(maxlen=30)
        self.paused = False
        self._anims: list = []

    # ---------- 消息 ----------
    def push(self, msg: WeChatMessage):
        if len(self.active) >= int(self.cfg.get("max_visible", 3)):
            self.pending.append(msg)
            return
        self._spawn(msg)

    def _spawn(self, msg: WeChatMessage):
        toast = Toast(msg, self.cfg, on_open_wechat=self.on_open_wechat)
        toast.closed.connect(self._on_closed)
        self.active.insert(0, toast)      # 最新的排最前
        toast.appear()
        self._relayout()

    def _on_closed(self, toast):
        if toast in self.active:
            self.active.remove(toast)
        self._relayout()
        if self.pending and len(self.active) < int(self.cfg.get("max_visible", 3)):
            self._spawn(self.pending.popleft())

    def close_all(self):
        for toast in list(self.active):
            toast.close()
            toast.deleteLater()
        self.active.clear()
        self.pending.clear()

    # ---------- 布局 ----------
    def _relayout(self):
        """按卡片的视觉尺寸排布，阴影留白不计入间距。"""
        screen = QGuiApplication.primaryScreen()
        geo: QRect = screen.availableGeometry()
        margin = int(self.cfg.get("margin", 22))
        gap = int(self.cfg.get("gap", 8))
        pos = self.cfg.get("position", "top-right")

        right = "right" in pos
        bottom = "bottom" in pos

        cursor = 0
        for toast in self.active:
            s = toast.shadow
            if right:
                wx = geo.x() + geo.width() - margin - toast.card_w - s
            else:
                wx = geo.x() + margin - s

            if bottom:
                wy = geo.y() + geo.height() - margin - cursor - toast.card_h - s
            else:
                wy = geo.y() + margin + cursor - s

            self._move_to(toast, QPoint(int(wx), int(wy)))
            cursor += toast.card_h + gap

    def _move_to(self, toast: Toast, target: QPoint):
        if toast.pos() == target:
            return
        if not toast.isVisible():
            toast.move(target)
            return
        anim = QPropertyAnimation(toast, b"pos", self)
        anim.setDuration(180)
        anim.setStartValue(toast.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anims.append(anim)
        if len(self._anims) > 40:
            self._anims = self._anims[-20:]
