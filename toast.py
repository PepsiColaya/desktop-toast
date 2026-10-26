# -*- coding: utf-8 -*-
"""通知悬浮卡片（Qt 绘制：圆角、阴影、淡入淡出、多条堆叠）。"""
from __future__ import annotations

import os
import re
from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
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

# 自定义配色的兜底值：用户把颜色写坏时按这套走，不至于变成纯黑一片
_CUSTOM_FALLBACK = THEMES["dark"]


def _qcolor(val, fallback: QColor) -> QColor:
    """把配置里的颜色字符串转成 QColor，非法时回落到 fallback。

    QColor 遇到 "#GGG" 这类字符串不会报错，只会得到一个 isValid() 为 False
    的对象，直接拿去画就是全黑，所以这里必须显式判断。
    """
    c = QColor(str(val or "").strip())
    return c if c.isValid() else QColor(fallback)


def resolve_theme(cfg: dict) -> dict:
    """按配置解析出实际使用的配色。

    ``dark`` / ``light`` 用预置配色；``custom`` 则读用户选的四项颜色
    （背景 / 边框 / 标题 / 正文）。返回结构固定是
    ``{"bg": QColor, "border": QColor, "title": str, "body": str}``。
    """
    name = str(cfg.get("theme", "dark") or "dark")
    if name != "custom":
        return THEMES.get(name, _CUSTOM_FALLBACK)

    bg = _qcolor(cfg.get("custom_bg"), _CUSTOM_FALLBACK["bg"])
    border = _qcolor(cfg.get("custom_border"), _CUSTOM_FALLBACK["border"])
    title = _qcolor(cfg.get("custom_title"), QColor(_CUSTOM_FALLBACK["title"]))
    body = _qcolor(cfg.get("custom_body"), QColor(_CUSTOM_FALLBACK["body"]))
    return {
        "bg": bg,
        "border": border,
        "title": title.name().upper(),
        "body": body.name().upper(),
    }

# 头像占位色：成对渐变，按名字散列固定挑选
AVATAR_GRADIENTS = [
    ("#6EA8FE", "#3B6FD4"),
    ("#F0A868", "#D9614C"),
    ("#4ED4A0", "#2FB38A"),
    ("#B48CE8", "#7C4DD6"),
    ("#F08A9E", "#D14A6B"),
    ("#5CC2E8", "#2E86C1"),
    ("#E8C468", "#C79A2E"),
    ("#8A94E8", "#5B67C7"),
]

AVATAR_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# 折行用的切分单位：显式换行 / 英文单词 / 连续空白 / 其余单字符（中文按字断行）
_TOKEN_RE = re.compile(r"\n|[A-Za-z0-9][A-Za-z0-9'’\-_.@:/]*|[ \t]+|.", re.S)

_avatar_cache: dict = {}


def avatar_gradient(name: str) -> tuple[str, str]:
    if not name:
        return AVATAR_GRADIENTS[0]
    return AVATAR_GRADIENTS[sum(ord(c) for c in name) % len(AVATAR_GRADIENTS)]


def safe_filename(name: str) -> str:
    """把会话名转成可用的文件名（去掉 Windows 非法字符）。"""
    bad = '\\/:*?"<>|'
    out = "".join("_" if c in bad else c for c in (name or "").strip())
    return out.rstrip(". ") or "_"


def load_avatar(name: str, avatar_dir: str) -> Optional[QPixmap]:
    """在头像目录里按会话名找图片，命中则返回，带 mtime 缓存。"""
    if not avatar_dir or not name:
        return None

    base = os.path.join(avatar_dir, safe_filename(name))
    for ext in AVATAR_EXTS:
        path = base + ext
        if not os.path.exists(path):
            continue
        try:
            key = (path, os.path.getmtime(path))
        except OSError:
            continue
        if key in _avatar_cache:
            return _avatar_cache[key]
        pm = QPixmap(path)
        pm = None if pm.isNull() else pm
        _avatar_cache[key] = pm
        return pm
    return None


def _wrap_all(text: str, fm: QFontMetrics, max_width: int) -> list[str]:
    """把整段文字折成若干行，不做行数限制。"""
    lines: list[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        lines.append(cur)
        cur = ""

    for tok in _TOKEN_RE.findall(text):
        if tok == "\n":
            flush()
            continue
        if not cur and not tok.strip():
            continue                                   # 行首空白不占位
        if fm.horizontalAdvance(cur + tok) <= max_width:
            cur += tok
            continue

        if cur:                                        # 当前行放不下，换行
            flush()
            tok = tok.lstrip()
            if not tok:
                continue
            if fm.horizontalAdvance(tok) <= max_width:
                cur = tok
                continue

        # 单个 token 比整行还宽（超长英文串 / 链接），退化成逐字符硬切
        for ch in tok:
            if cur and fm.horizontalAdvance(cur + ch) > max_width:
                flush()
            cur += ch

    flush()
    return lines


def wrap_text(text: str, fm: QFontMetrics, max_width: int, max_lines: int = 2) -> list[str]:
    """按像素宽度折行，超出 max_lines 时最后一行加省略号。

    英文按单词断开（不会把 hello 拆成 hel/lo），中文按字断开。
    """
    max_width = max(20, int(max_width))
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ["（新消息）"]

    lines = [ln.rstrip() for ln in _wrap_all(text, fm, max_width)]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        return ["（新消息）"]
    if len(lines) <= max_lines:
        return lines

    out = lines[:max_lines]
    tail = out[-1]
    while tail and fm.horizontalAdvance(tail + "…") > max_width:
        tail = tail[:-1]
    out[-1] = tail.rstrip() + "…"
    return out


class Toast(QWidget):
    """单条消息的悬浮卡片。所有尺寸由 config 推导，便于实时调参。"""

    closed = Signal(object)

    def __init__(self, msg: WeChatMessage, cfg: dict,
                 on_open: Optional[Callable[[WeChatMessage], None]] = None):
        super().__init__(None)
        self.msg = msg
        self.cfg = cfg
        self.on_open = on_open or (lambda _m: None)
        self.theme = resolve_theme(cfg)

        self._hovering = False
        self._closing = False
        self._count = 1
        self._anims: list = []

        # ---- 由配置推导尺寸 ----
        k = float(cfg.get("scale", 1.0))
        self.avatar_dir = cfg.get("avatar_dir") or ""
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

        # 整张卡片都能点（打开来源应用），给个手型光标，不然看不出可点
        if cfg.get("click_to_open_source", True):
            self.setCursor(Qt.PointingHandCursor)

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
        self.text_x = self.pad + self.avatar + self.text_gap
        self.text_w = max(20, self.card_w - self.text_x - self.pad)

        self._apply_text()
        self._build_labels()
        self._apply_geometry()

        # ---- 动画 ----
        self.setWindowOpacity(0.0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)

    # ---------- 排版计算 ----------
    def _apply_text(self) -> None:
        """根据当前消息与合并条数，算出标题、正文行与卡片高度。"""
        title = self.msg.display_title
        if self._count > 1:
            title = f"{title}（{self._count}）"

        fm_title = QFontMetrics(self.f_title)
        self.title_text = fm_title.elidedText(title, Qt.ElideRight, self.text_w)

        # 关掉「显示详细消息」时，正文只留一句占位，避免别人一眼看到内容
        content = self.msg.content
        if not self.cfg.get("show_content", True):
            content = "有一条新消息"
        self.body_lines = wrap_text(content, QFontMetrics(self.f_body),
                                    self.text_w, max_lines=2)

        self.card_h = (self.pad * 2 + self.title_h + self.title_gap
                       + len(self.body_lines) * self.line_h)
        self.card_h = max(self.card_h, self.pad * 2 + self.avatar)

    def _build_labels(self) -> None:
        self.lb_title = QLabel(self)
        self.lb_title.setFont(self.f_title)
        self.lb_title.setStyleSheet(f"color: {self.theme['title']}; background: transparent;")

        self.lb_body = QLabel(self)
        self.lb_body.setFont(self.f_body)
        self.lb_body.setStyleSheet(f"color: {self.theme['body']}; background: transparent;")

        for lb in (self.lb_title, self.lb_body):
            lb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lb.setContentsMargins(0, 0, 0, 0)
            lb.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._sync_labels()

    def _sync_labels(self) -> None:
        self.lb_title.setText(self.title_text)
        self.lb_body.setText("\n".join(self.body_lines))

    def _apply_geometry(self) -> None:
        """尺寸变化后重排窗口与文字控件（坐标需加上阴影留白）。"""
        s = self.shadow
        self.resize(self.card_w + s * 2, self.card_h + s * 2)
        self.lb_title.setGeometry(s + self.text_x, s + self.pad, self.text_w, self.title_h)
        self.lb_body.setGeometry(
            s + self.text_x, s + self.pad + self.title_h + self.title_gap,
            self.text_w, len(self.body_lines) * self.line_h,
        )

    def update_message(self, msg: WeChatMessage) -> bool:
        """同一会话来了新消息：原地更新内容并累加条数，避免刷屏。"""
        if self._closing:
            return False
        self.msg = msg
        self._count += 1
        self._apply_text()
        self._sync_labels()
        self._apply_geometry()
        self.update()
        if not self._hovering:
            self._restart_timer()
        return True

    @property
    def is_closing(self) -> bool:
        return self._closing

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

        # 头像：优先用 avatars 目录里的真实头像，否则渐变首字兜底
        d = self.avatar
        ax = s + self.pad
        ay = s + (self.card_h - d) / 2
        self._draw_avatar(p, QRectF(ax, ay, d, d))

    def _draw_avatar(self, p: QPainter, rect: QRectF):
        d = rect.width()
        clip = QPainterPath()
        clip.addEllipse(rect)

        pm = load_avatar(self.msg.source, self.avatar_dir)
        p.save()
        p.setClipPath(clip)

        if pm is not None and not pm.isNull():
            # 放大两倍渲染再缩小，边缘更清晰
            scaled = pm.scaled(int(d * 2), int(d * 2), Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(2.0)
            lw, lh = scaled.width() / 2.0, scaled.height() / 2.0
            p.drawPixmap(QPointF(rect.x() + (d - lw) / 2, rect.y() + (d - lh) / 2), scaled)
        else:
            c1, c2 = avatar_gradient(self.msg.source)
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor(c1))
            grad.setColorAt(1.0, QColor(c2))
            p.fillPath(clip, grad)

            p.setPen(QColor("#FFFFFF"))
            p.setFont(self.f_avatar)
            initial = (self.msg.source or "?")[0]
            p.drawText(rect.adjusted(0, -1, 0, -1), Qt.AlignCenter, initial)

        p.restore()

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
            if self.cfg.get("click_to_open_source", True):
                self.on_open(self.msg)
            self.fade_out()
        elif evt.button() == Qt.RightButton:
            self._show_menu(evt.globalPosition().toPoint())

    def _show_menu(self, pos: QPoint):
        m = QMenu(self)
        act_open = QAction("打开来源应用", self)
        act_open.triggered.connect(lambda: self.on_open(self.msg))
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
                 on_open: Optional[Callable[[WeChatMessage], None]] = None):
        super().__init__()
        self.cfg = cfg
        self.app = app
        self.on_open = on_open or (lambda _m: None)

        self.active: list[Toast] = []
        self.pending: deque[WeChatMessage] = deque(maxlen=30)
        self.paused = False
        self._anims: list = []

    # ---------- 消息 ----------
    def push(self, msg: WeChatMessage):
        # 同一会话还在屏幕上：直接更新那张卡，不新增一条
        if self.cfg.get("merge_same_source", True):
            for toast in self.active:
                if toast.msg.source == msg.source and not toast.is_closing:
                    toast.update_message(msg)
                    self._relayout()
                    return

        if len(self.active) >= int(self.cfg.get("max_visible", 3)):
            self.pending.append(msg)
            return
        self._spawn(msg)

    def _spawn(self, msg: WeChatMessage):
        toast = Toast(msg, self.cfg, on_open=self.on_open)
        toast.closed.connect(self._on_closed)
        self.active.insert(0, toast)      # 最新的排最前
        self._relayout()                  # 先摆到目标屏幕，避免在副屏用户眼前闪一下主屏
        toast.appear()

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
    def _target_screen(self):
        """按配置挑选屏幕：默认跟随鼠标，多屏办公时卡片不会跑到另一块屏上。"""
        if self.cfg.get("screen", "cursor") == "cursor":
            scr = QGuiApplication.screenAt(QCursor.pos())
            if scr is not None:
                return scr
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            return scr
        screens = QGuiApplication.screens()
        return screens[0] if screens else None

    def _relayout(self):
        """按卡片的视觉尺寸排布，阴影留白不计入间距。"""
        screen = self._target_screen()
        if screen is None:
            return
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
