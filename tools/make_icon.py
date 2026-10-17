"""Render the Print Prep app icon (PNG + multi-size ICO) with QPainter. Original artwork.

An abstract composition after Kandinsky's "Several Circles": translucent glowing discs
on a night-blue ground, blended like light, read at once as lenses, bokeh and paint.
Viewfinder corners frame it, so the picture is about photography made into art.

Usage: python tools/make_icon.py
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

ROOT = Path(__file__).resolve().parents[1]


def squircle(r, k=.235):
    path = QPainterPath()
    path.addRoundedRect(r, r.width() * k, r.height() * k)
    return path


def disc(p, c, radius, inner, outer, glow=0.):
    """A disc with a soft luminous edge, like the circles in Kandinsky's late works."""
    if glow:
        halo = QRadialGradient(c, radius * (1 + glow))
        g = QColor(outer)
        g.setAlpha(110)
        halo.setColorAt(radius / (radius * (1 + glow)) * .92, g)
        g.setAlpha(0)
        halo.setColorAt(1, g)
        p.setBrush(halo)
        p.drawEllipse(c, radius * (1 + glow), radius * (1 + glow))
    grad = QRadialGradient(QPointF(c.x() - radius * .3, c.y() - radius * .35), radius * 1.35)
    grad.setColorAt(0, QColor(inner))
    grad.setColorAt(1, QColor(outer))
    p.setBrush(grad)
    p.drawEllipse(c, radius, radius)


def render(size):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 1024, size / 1024)
    small = size <= 32
    body = QRectF(40, 40, 944, 944)
    shape = squircle(body)
    ground = QLinearGradient(body.topLeft(), body.bottomRight())
    ground.setColorAt(0, QColor('#242a5c'))
    ground.setColorAt(.55, QColor('#141634'))
    ground.setColorAt(1, QColor('#0b0b1c'))
    p.fillPath(shape, ground)
    p.setClipPath(shape)
    p.setPen(Qt.PenStyle.NoPen)
    # Faint dust of tiny stars — the "night" of Several Circles.
    if not small:
        for x, y, r in ((215, 600, 5), (860, 600, 4), (600, 170, 4), (470, 930, 3), (905, 170, 3), (600, 890, 4)):
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawEllipse(QPointF(x, y), r, r)
    # The great disc: deep blue with a black core, a lens and a planet at once.
    disc(p, QPointF(445, 560), 292, '#3a5bff', '#16207e', glow=.18)
    p.setBrush(QColor(8, 9, 26, 240))
    p.drawEllipse(QPointF(462, 578), 128, 128)
    p.setBrush(QColor(255, 255, 255, 46))
    p.drawEllipse(QPointF(420, 538), 28, 28)
    # Translucent discs mixing like light where they overlap.
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
    disc(p, QPointF(705, 335), 160, '#ff6fa8', '#b8155a', glow=.22)
    disc(p, QPointF(262, 292), 64, '#8ff3ff', '#0f9fd0', glow=.3)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.setOpacity(.94)
    disc(p, QPointF(690, 690), 100, '#ffe15a', '#f08c00', glow=.28)
    p.setOpacity(1)
    disc(p, QPointF(815, 820), 32, '#ff9b6b', '#e2401c', glow=.3)
    # The draughtsman's gestures: a line that grazes the discs, an arc, a triangle and a small
    # chequer — Kandinsky's vocabulary, the chequer doubling as a printer's halftone.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 200), 26 if small else 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(255, 930) if small else QPointF(300, 905), QPointF(930, 470) if small else QPointF(905, 495))
    if not small:
        p.setPen(QPen(QColor(255, 255, 255, 130), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(705 - 210, 335 - 210, 420, 420), 195 * 16, 110 * 16)
        tri = QPainterPath()
        tri.moveTo(470, 150)
        tri.lineTo(540, 262)
        tri.lineTo(400, 262)
        tri.closeSubpath()
        p.setPen(QPen(QColor('#ffe15a'), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(tri)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    p.setBrush(QColor(255, 255, 255, 185))
                    p.drawRect(QRectF(505 + i * 28, 815 + j * 28, 28, 28))
    # Viewfinder corners: the composition is seen through a camera.
    if size >= 48:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 165), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        m, L = 120, 84
        for cx, cy, dx, dy in ((m, m, 1, 1), (1024 - m, m, -1, 1), (m, 1024 - m, 1, -1), (1024 - m, 1024 - m, -1, -1)):
            corner = QPainterPath()
            corner.moveTo(cx, cy + dy * L)
            corner.lineTo(cx, cy)
            corner.lineTo(cx + dx * L, cy)
            p.drawPath(corner)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 34), 5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(squircle(body.adjusted(2.5, 2.5, -2.5, -2.5)))
    p.end()
    return img


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    assets = ROOT / 'assets'
    render(1024).save(str(assets / 'printprep_1024.png'))
    render(256).save(str(assets / 'printprep.png'))
    from PIL import Image
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = []
    for n in sizes:
        tmp = assets / f'.icon_{n}.png'
        render(n).save(str(tmp))
        frames.append(Image.open(tmp).convert('RGBA'))
        tmp.unlink()
    frames[-1].save(assets / 'printprep.ico', sizes=[(n, n) for n in sizes], append_images=frames[:-1])
    print('icon written')


if __name__ == '__main__':
    main()
