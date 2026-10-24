# -*- coding: utf-8 -*-
"""把卡片渲染到干净背景上，生成展示图（不截桌面）。

用法：
    python render_preview.py            # 用当前 config.json 渲染
    python render_preview.py --demo     # 用默认参数渲染
"""
import sys
import time

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

import config as cfgmod
from toast import Toast
from watcher import WeChatMessage

app = QApplication(sys.argv)

cfg = cfgmod.load()
if "--demo" in sys.argv:
    cfg.update({"card_width": 340, "scale": 1.0, "radius": 14,
                "shadow": 16, "opacity": 0.96, "gap": 8})

samples = [
    WeChatMessage("示例群", "张三", "这个版本的接口文档我下午更新一下，你们先按旧的对", time.time(), 1),
    WeChatMessage("李四", "", "好的，收到，我这边先联调", time.time(), 2),
]

toasts = []
for m in samples:
    t = Toast(m, cfg)
    t.setWindowOpacity(1.0)
    t.show()
    toasts.append(t)

app.processEvents()

DPR = 2.0
gap = int(cfg["gap"])
shadow = max(t.shadow for t in toasts)
pad_x, pad_y = 30, 26

total_w = max(t.card_w for t in toasts) + shadow * 2 + pad_x * 2
total_h = (sum(t.card_h for t in toasts) + gap * (len(toasts) - 1)
           + shadow * 2 + pad_y * 2)

canvas = QPixmap(int(total_w * DPR), int(total_h * DPR))
canvas.setDevicePixelRatio(DPR)
canvas.fill(Qt.transparent)

p = QPainter(canvas)
p.setRenderHint(QPainter.Antialiasing, True)
p.setRenderHint(QPainter.SmoothPixmapTransform, True)

grad = QLinearGradient(0, 0, total_w, total_h)
grad.setColorAt(0, QColor("#EDF1F7"))
grad.setColorAt(1, QColor("#DCE3EE"))
p.fillRect(canvas.rect(), grad)

y = pad_y
for t in toasts:
    shot = QPixmap(int(t.width() * DPR), int(t.height() * DPR))
    shot.setDevicePixelRatio(DPR)
    shot.fill(Qt.transparent)
    t.render(shot)
    p.drawPixmap(QPoint(pad_x, int(y)), shot)
    y += t.card_h + gap
p.end()

canvas.save("showcase.png")
print(f"saved showcase.png {canvas.width()}x{canvas.height()}  "
      f"width={cfg['card_width']} scale={cfg['scale']} opacity={cfg['opacity']}")

for t in toasts:
    t.close()
