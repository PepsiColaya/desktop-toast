# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（绿底圆角 + 微字），用于 exe 与托盘。"""
import sys

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

SIZE = 256
pm = QPixmap(SIZE, SIZE)
pm.fill(Qt.transparent)

p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
p.setPen(Qt.NoPen)
p.setBrush(QColor("#07C160"))
p.drawRoundedRect(QRectF(6, 6, SIZE - 12, SIZE - 12), 58, 58)

p.setPen(QColor("#FFFFFF"))
f = QFont("Microsoft YaHei UI")
f.setPixelSize(146)
f.setWeight(QFont.Bold)
p.setFont(f)
p.drawText(pm.rect(), Qt.AlignCenter, "微")
p.end()

pm.save("icon_256.png")

img = Image.open("icon_256.png").convert("RGBA")
img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("saved icon.ico")
