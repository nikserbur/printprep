"""Photo viewer: fit/100%/200% with progressive sharp tiles, before/after split, crop
mode, safe-zone overlay, status overlay and the empty state."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import icons
from .controls import button, label
from .theme import T
from ..i18n import tr


def background(name):
    return T.get(f'viewer_{name}', T['viewer_dark'])


class FolderArt(QWidget):
    """A folder with photos peeking out and bobbing; they jump up while a folder is dragged over."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 96)
        self.t = 0.
        self.lift = 0.
        self.active = False
        from .app_settings import animations_on
        self.animated = animations_on()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def showEvent(self, e):
        if self.animated:
            self.timer.start()

    def hideEvent(self, e):
        self.timer.stop()

    def set_active(self, on):
        self.active = on
        if not self.animated:
            self.lift = 1. if on else 0.
            self.update()

    def _tick(self):
        self.t += .033
        self.lift += ((1. if self.active else 0.) - self.lift) * .18
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        accent = QColor(T['accent'])
        back = QColor(accent)
        back.setAlpha(150)
        # Folder back with tab.
        path = QPainterPath()
        path.addRoundedRect(QRectF(w / 2 - 52, 22, 104, 66), 9, 9)
        path.addRoundedRect(QRectF(w / 2 - 52, 15, 40, 16), 6, 6)
        p.fillPath(path.simplified(), back)
        # Photos: sky, sunset and forest, each bobbing with its own phase.
        colours = (('#8fc0ff', '#4c7bd9'), ('#ffc98f', '#e0663f'), ('#a6e3b0', '#3f9a62'))
        for i, (sky, ground) in enumerate(colours):
            bob = (math.sin(self.t * 2.2 + i * 1.3) * 3 if self.animated else 0) - self.lift * (10 + 4 * i)
            angle = (-12, 0, 12)[i] * (1 + .3 * self.lift)
            p.save()
            p.translate(w / 2 + (i - 1) * 24, 48 + bob)
            p.rotate(angle)
            card = QRectF(-20, -26, 40, 34)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#ffffff'))
            p.drawRoundedRect(card, 4, 4)
            pic = card.adjusted(4, 4, -4, -8)
            p.fillRect(pic, QColor(sky))
            hill = QPainterPath()
            hill.moveTo(pic.left(), pic.bottom())
            hill.lineTo(pic.left() + pic.width() * .35, pic.top() + pic.height() * .45)
            hill.lineTo(pic.left() + pic.width() * .6, pic.top() + pic.height() * .7)
            hill.lineTo(pic.right(), pic.top() + pic.height() * .35)
            hill.lineTo(pic.right(), pic.bottom())
            hill.closeSubpath()
            p.fillPath(hill, QColor(ground))
            p.restore()
        # Folder front.
        front = QPainterPath()
        front.moveTo(w / 2 - 56, 50)
        front.lineTo(w / 2 + 56, 50)
        front.lineTo(w / 2 + 50, 88)
        front.lineTo(w / 2 - 50, 88)
        front.closeSubpath()
        g = QLinearGradient(0, 50, 0, 88)
        g.setColorAt(0, QColor(T['accent_hover']))
        g.setColorAt(1, accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawPath(front)
        p.setPen(QPen(QColor(255, 255, 255, 90), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(w / 2 - 16, 72), QPointF(w / 2 + 16, 72))


class EmptyState(QWidget):
    openRequested = Signal()
    recentRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(2)
        self.card = QFrame()
        self.card.setObjectName('Drop')
        self.card.setMaximumWidth(560)
        self.card.setStyleSheet(f'''#Drop {{ background: {T["panel"]}; border: 1.5px dashed {T["border_strong"]}; border-radius: 18px; }}
                                    #Drop[active="true"] {{ border-color: {T["accent"]}; background: {T["drop_active"]}; }}''')
        box = QVBoxLayout(self.card)
        box.setContentsMargins(40, 36, 40, 32)
        box.setSpacing(10)
        self.art = FolderArt()
        box.addWidget(self.art, 0, Qt.AlignmentFlag.AlignHCenter)
        title = label(tr('Перетащите папку с фотографиями'), 'Big')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        hint = label(tr('Все снимки папки подготовятся одним пресетом. Оригиналы не меняются —\n'
                     'результат появится в подпапке PrintPrep_… рядом с ними.'), 'Muted')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(hint)
        box.addSpacing(8)
        self.open = button(tr('Выбрать папку…'), self.openRequested.emit, 'Primary', 'folder')
        self.open.setMinimumWidth(200)
        box.addWidget(self.open, 0, Qt.AlignmentFlag.AlignHCenter)
        formats = label(tr('JPEG · TIFF 8/16 бит · PNG · WebP · BMP'), 'Hint')
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(formats)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        box.addSpacing(6)
        box.addLayout(self.recent_box)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.card, 1)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch(3)

    def set_recent(self, folders):
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not folders:
            return
        head = label(tr('НЕДАВНИЕ ПАПКИ'), 'Eyebrow')
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_box.addWidget(head)
        for path in folders[:5]:
            b = QPushButton(path)
            b.setObjectName('Ghost')
            b.setIcon(icons.icon('folder', T['text3']))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(path)
            b.setStyleSheet('text-align: left; padding: 6px 10px;')
            b.clicked.connect(lambda _=False, p=path: self.recentRequested.emit(p))
            self.recent_box.addWidget(b)

    def set_drag_active(self, active):
        self.art.set_active(active)
        self.card.setProperty('active', 'true' if active else 'false')
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)


class Viewer(QWidget):
    roiRequested = Signal(tuple)
    zoomChanged = Signal(object)
    cropEdited = Signal(float, float, float)       # center_x, center_y, zoom
    compareMoved = Signal(float)

    PAD = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)
        self.mode = 'empty'
        self.bg = background('dark')
        self.canvas = (1, 1)
        self.fit_img = self.fit_before = None
        self.roi_img = self.roi_before = None
        self.roi_region = None
        self.zoom = 'fit'
        self.center = QPointF(.5, .5)       # normalised canvas point at view centre
        self.compare = False
        self.split = .5
        self.safe = None                    # (px_per_mm in canvas px, mm)
        self.loading_aspect = 1.5
        self.status_text = ''
        self.status_progress = None
        self.view_mode = 'result'            # result | split | original
        self.neural_badge = None             # (text, progress fraction or None)
        self.status_visible = False
        self._drag = None
        self.crop = None                    # dict(image, k, rect(x0,y0,x1,y1) norm, ratio)
        self.spin = 0
        self.empty = EmptyState(self)
        self.status_timer = QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.timeout.connect(self._show_status)
        self.anim = QTimer(self)
        self.anim.setInterval(16)
        self.anim.timeout.connect(self._tick)
        self.roi_timer = QTimer(self)
        self.roi_timer.setSingleShot(True)
        self.roi_timer.setInterval(140)
        self.roi_timer.timeout.connect(self._request_roi)
        self.setAccessibleName(tr('Просмотр снимка'))

    # ------------------------------------------------------------ public API
    def set_background(self, name):
        self.bg = background(name)
        self.update()

    def set_empty(self, recent=()):
        self.mode = 'empty'
        self.fit_img = self.fit_before = self.roi_img = self.roi_before = None
        self.empty.set_recent(list(recent))
        self.empty.show()
        self.clear_status()
        self.update()

    def set_loading(self, aspect, thumb=None):
        self.empty.hide()
        self.mode = 'loading'
        self.loading_aspect = aspect or 1.5
        self.loading_thumb = thumb if thumb is not None and not thumb.isNull() else None
        self.fit_img = self.fit_before = None
        self.clear_roi()
        self.anim.start()
        self.update()

    def set_canvas(self, size, reset=False):
        changed = tuple(size) != tuple(self.canvas)
        self.canvas = tuple(size)
        if reset:
            self.zoom = 'fit'
            self.center = QPointF(.5, .5)
            self.zoomChanged.emit('fit')
        if changed or reset:
            self.clear_roi()

    def set_fit(self, image, before=None):
        self.empty.hide()
        if self.mode in ('loading', 'empty'):
            self.mode = 'image'
        self.fit_img, self.fit_before = image, before
        if self.mode != 'crop':
            self.mode = 'image'
        self._update_anim()
        self.update()
        if self.zoom != 'fit':
            self.roi_timer.start()

    def set_roi(self, image, region, before=None):
        self.roi_img, self.roi_region, self.roi_before = image, region, before
        self.update()

    def clear_roi(self):
        self.roi_img = self.roi_before = self.roi_region = None
        self.update()

    def set_zoom(self, zoom, anchor=None):
        if zoom == self.zoom:
            return
        if zoom != 'fit' and anchor is not None:
            self.center = self._canvas_point(anchor)
        self.zoom = zoom
        self.clear_roi()
        self._clamp_center()
        self.update()
        self.zoomChanged.emit(zoom)
        if zoom != 'fit':
            self.roi_timer.start()

    def set_compare(self, on):
        self.set_view_mode('split' if on else 'result')

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.compare = mode == 'split'
        self.update()
        if self.zoom != 'fit':
            self.roi_timer.start()

    def set_neural_badge(self, text=None, progress=None):
        self.neural_badge = (text, progress) if text else None
        self._update_anim()
        self.update()

    def set_safe_zone(self, px_per_mm, mm=3):
        self.safe = (px_per_mm, mm) if px_per_mm else None
        self.update()

    def set_status(self, text, progress=None):
        self.status_text, self.status_progress = text, progress
        if self.status_visible:
            self.update()
        elif not self.status_timer.isActive():
            self.status_timer.start(180)

    def clear_status(self):
        self.status_timer.stop()
        self.status_visible = False
        self.status_text = ''
        self._update_anim()
        self.update()

    def enter_crop(self, image, k, rect, ratio):
        self.empty.hide()
        self.mode = 'crop'
        self.crop = dict(image=image, k=k, rect=list(rect), ratio=ratio)
        self.update()

    def update_crop_image(self, image, k, rect, ratio):
        if self.mode == 'crop' and self.crop is not None:
            if not (self._drag and self._drag[0].startswith('crop')):
                self.crop.update(image=image, k=k, rect=list(rect), ratio=ratio)
            else:
                self.crop.update(image=image, k=k)
            self.update()

    def exit_crop(self):
        self.crop = None
        self.mode = 'image' if self.fit_img is not None else 'loading'
        self.update()

    def visible_region(self):
        """Visible canvas rect at 100% (x, y, w, h), or None in fit mode."""
        if self.zoom == 'fit':
            return None
        disp = self._display_rect()
        s = disp.width() / self.canvas[0]
        x0 = max(0., (0 - disp.left()) / s)
        y0 = max(0., (0 - disp.top()) / s)
        x1 = min(self.canvas[0], (self.width() - disp.left()) / s)
        y1 = min(self.canvas[1], (self.height() - disp.top()) / s)
        if x1 <= x0 or y1 <= y0:
            return None
        return int(x0), int(y0), int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))

    # ------------------------------------------------------------ geometry
    def _dpr(self):
        return self.devicePixelRatioF() or 1.

    def _display_rect(self):
        W, H = self.canvas
        if self.zoom == 'fit':
            avail_w, avail_h = self.width() - 2 * self.PAD, self.height() - 2 * self.PAD
            s = max(1e-6, min(avail_w / W, avail_h / H))
            w, h = W * s, H * s
            return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        s = float(self.zoom) / self._dpr()
        w, h = W * s, H * s
        cx, cy = self.center.x() * w, self.center.y() * h
        return QRectF(self.width() / 2 - cx, self.height() / 2 - cy, w, h)

    def _canvas_point(self, pos):
        disp = self._display_rect()
        return QPointF(min(1, max(0, (pos.x() - disp.left()) / disp.width())),
                       min(1, max(0, (pos.y() - disp.top()) / disp.height())))

    def _clamp_center(self):
        if self.zoom == 'fit':
            return
        W, H = self.canvas
        s = float(self.zoom) / self._dpr()
        hw, hh = self.width() / (2 * W * s), self.height() / (2 * H * s)
        x = .5 if hw >= .5 else min(1 - hw, max(hw, self.center.x()))
        y = .5 if hh >= .5 else min(1 - hh, max(hh, self.center.y()))
        self.center = QPointF(x, y)

    def _crop_rects(self):
        img = self.crop['image']
        avail = QRectF(self.PAD, self.PAD, self.width() - 2 * self.PAD, self.height() - 2 * self.PAD)
        s = min(avail.width() / img.width(), avail.height() / img.height())
        w, h = img.width() * s, img.height() * s
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        x0, y0, x1, y1 = self.crop['rect']
        return r, QRectF(r.left() + x0 * w, r.top() + y0 * h, (x1 - x0) * w, (y1 - y0) * h)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.bg))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.mode == 'loading':
            self._paint_skeleton(p)
        elif self.mode == 'crop' and self.crop:
            self._paint_crop(p)
        elif self.mode == 'image' and self.fit_img is not None:
            self._paint_image(p)
        if self.status_visible and self.status_text:
            self._paint_status(p)
        if self.neural_badge and self.mode in ('image', 'loading'):
            self._paint_neural(p)

    def _paint_skeleton(self, p):
        avail_w, avail_h = self.width() - 2 * self.PAD, self.height() - 2 * self.PAD
        a = self.loading_aspect
        w = min(avail_w, avail_h * a)
        h = w / a
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        thumb = getattr(self, 'loading_thumb', None)
        if thumb is not None:
            # Show the filmstrip thumbnail at once; the sharp preview replaces it in a moment.
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, thumb)
        else:
            p.setBrush(QColor(T['skeleton']))
            p.drawRoundedRect(r, 6, 6)
        x = r.left() + (self.spin % 120) / 120 * (r.width() + 300) - 150
        g = QLinearGradient(x - 150, 0, x + 150, 0)
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(.5, QColor(255, 255, 255, 14))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(g)
        p.drawRoundedRect(r, 6, 6)

    def _draw_layer(self, p, disp, fit, roi):
        smooth = self.zoom == 'fit' or float(self.zoom) <= 1
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if fit is not None:
            p.drawImage(disp, fit)
        if roi is not None and self.roi_region:
            s = disp.width() / self.canvas[0]
            x, y, w, h = self.roi_region
            target = QRectF(disp.left() + x * s, disp.top() + y * s, w * s, h * s)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
            p.drawImage(target, roi)

    def _paint_image(self, p):
        disp = self._display_rect()
        p.setPen(Qt.PenStyle.NoPen)
        shadow = disp.adjusted(-1, -1, 1, 1)
        p.fillRect(shadow, QColor(0, 0, 0, 90))
        if self.view_mode == 'original' and self.fit_before is not None:
            self._draw_layer(p, disp, self.fit_before, self.roi_before)
            self._pill(p, tr('Исходник · без обработки'), QPointF(self.width() / 2, 26))
        elif self.compare and self.fit_before is not None:
            split_x = self.width() * self.split
            p.save()
            p.setClipRect(QRectF(0, 0, split_x, self.height()))
            self._draw_layer(p, disp, self.fit_before, self.roi_before)
            p.restore()
            p.save()
            p.setClipRect(QRectF(split_x, 0, self.width() - split_x, self.height()))
            self._draw_layer(p, disp, self.fit_img, self.roi_img)
            p.restore()
            self._paint_split(p, split_x)
        else:
            self._draw_layer(p, disp, self.fit_img, self.roi_img)
        if self.zoom != 'fit':
            text = (tr('1:1 — пиксель файла = пиксель экрана') if float(self.zoom) == 1
                    else tr('{v:g}:1 — увеличено для проверки деталей', v=float(self.zoom)))
            self._pill(p, text, None, bottom_left=True)
        if self.safe and self.zoom == 'fit':
            px_mm, mm = self.safe
            s = disp.width() / self.canvas[0]
            inset = px_mm * mm * s
            if inset > 2:
                pen = QPen(QColor(255, 255, 255, 150), 1, Qt.PenStyle.DashLine)
                pen.setDashPattern([4, 4])
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(disp.adjusted(inset, inset, -inset, -inset))

    def _pill(self, p, text, centre=None, bottom_left=False):
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 22
        if bottom_left:
            r = QRectF(14, self.height() - 38, w, 24)
        else:
            r = QRectF(centre.x() - w / 2, centre.y() - 12, w, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(16, 17, 20, 215))
        p.drawRoundedRect(r, 12, 12)
        p.setPen(QColor(T['text']))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_neural(self, p):
        text, progress = self.neural_badge
        f = QFont(self.font())
        f.setPointSizeF(8.75)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(text)
        w, h = tw + 50, 40 if progress is not None else 30
        r = QRectF(self.width() - w - 16, self.height() - h - 16, w, h)
        p.setPen(QPen(QColor(155, 107, 255, 120), 1))
        p.setBrush(QColor(22, 18, 34, 235))
        p.drawRoundedRect(r, 12, 12)
        c = QPointF(r.left() + 18, r.top() + 15)
        p.drawPixmap(QRectF(c.x() - 8, c.y() - 8, 16, 16).toRect(), icons.pixmap('cpu', '#b591ff', 16))
        p.setPen(QColor('#e9e1ff'))
        p.drawText(QRectF(r.left() + 32, r.top(), tw + 10, 30), Qt.AlignmentFlag.AlignVCenter, text)
        if progress is not None:
            bar = QRectF(r.left() + 32, r.top() + 28, w - 44, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(QColor('#9b6bff'))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(.02, min(1, progress)), 4), 2, 2)

    def _paint_split(self, p, x):
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        c = QPointF(x, self.height() / 2)
        p.setBrush(QColor(20, 21, 24, 230))
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        p.drawEllipse(c, 15, 15)
        p.drawPixmap(QRectF(c.x() - 9, c.y() - 9, 18, 18).toRect(), icons.pixmap('compare', '#ffffff', 18))
        for text, left in ((tr('До'), True), (tr('После'), False)):
            f = QFont(self.font())
            f.setPointSizeF(9)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + 18
            r = QRectF(x - w - 12 if left else x + 12, 14, w, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 21, 24, 200))
            p.drawRoundedRect(r, 12, 12)
            p.setPen(QColor('#ffffff'))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_crop(self, p):
        img_rect, r = self._crop_rects()
        p.drawImage(img_rect, self.crop['image'])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        outer = QPainterPath()
        outer.addRect(img_rect)
        inner = QPainterPath()
        inner.addRect(r)
        p.drawPath(outer.subtracted(inner))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for f in (1 / 3, 2 / 3):
            p.drawLine(QPointF(r.left() + f * r.width(), r.top()), QPointF(r.left() + f * r.width(), r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + f * r.height()), QPointF(r.right(), r.top() + f * r.height()))
        p.setPen(QPen(QColor('#ffffff'), 1.5))
        p.drawRect(r)
        corner_pen = QPen(QColor('#ffffff'), 3)
        corner_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(corner_pen)
        L = 14
        for cx, cy, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * L))

    def _paint_status(self, p):
        f = QFont(self.font())
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self.status_text)
        w = tw + 54
        h = 34 if self.status_progress is None else 42
        r = QRectF((self.width() - w) / 2, 16, w, h)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(QColor(24, 25, 29, 235))
        p.drawRoundedRect(r, 12, 12)
        c = QPointF(r.left() + 20, r.top() + 17)
        p.setPen(QPen(QColor(255, 255, 255, 40), 2))
        p.drawEllipse(c, 7, 7)
        pen = QPen(QColor(T['accent_hover']), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(c.x() - 7, c.y() - 7, 14, 14), -self.spin * 6 * 16, 100 * 16)
        p.setPen(QColor(T['text']))
        p.drawText(QRectF(r.left() + 36, r.top(), tw + 10, 34), Qt.AlignmentFlag.AlignVCenter, self.status_text)
        if self.status_progress is not None:
            bar = QRectF(r.left() + 36, r.top() + 31, w - 50, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(QColor(T['accent']))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0, min(1, self.status_progress)), 4), 2, 2)

    # ------------------------------------------------------------ animation & status
    def _show_status(self):
        self.status_visible = True
        self._update_anim()
        self.update()

    def _update_anim(self):
        need = self.mode == 'loading' or (self.status_visible and bool(self.status_text))
        if need and not self.anim.isActive():
            self.anim.start()
        elif not need:
            self.anim.stop()

    def _tick(self):
        self.spin += 1
        self.update()

    # ------------------------------------------------------------ interaction
    def resizeEvent(self, e):
        self.empty.setGeometry(self.rect())
        self._clamp_center()
        if self.zoom != 'fit':
            self.roi_timer.start()
        super().resizeEvent(e)

    def _near_split(self, pos):
        return self.compare and abs(pos.x() - self.width() * self.split) < 18

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        if self.mode == 'crop' and self.crop:
            img_rect, r = self._crop_rects()
            corner = self._corner_at(pos, r)
            if corner is not None:
                self._drag = ('crop_corner', pos, list(self.crop['rect']), corner)
            elif r.contains(pos):
                self._drag = ('crop_move', pos, list(self.crop['rect']), None)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.mode != 'image':
            return
        if self._near_split(pos):
            self._drag = ('split', pos, self.split, None)
        elif self.zoom != 'fit':
            self._drag = ('pan', pos, QPointF(self.center), None)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _corner_at(self, pos, r):
        for i, c in enumerate((r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight())):
            if abs(pos.x() - c.x()) < 14 and abs(pos.y() - c.y()) < 14:
                return i
        return None

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag:
            if self.mode == 'crop' and self.crop:
                _, r = self._crop_rects()
                corner = self._corner_at(pos, r)
                self.setCursor(Qt.CursorShape.SizeFDiagCursor if corner in (0, 3) else Qt.CursorShape.SizeBDiagCursor
                               if corner in (1, 2) else Qt.CursorShape.OpenHandCursor if r.contains(pos) else Qt.CursorShape.ArrowCursor)
            elif self._near_split(pos):
                self.setCursor(Qt.CursorShape.SplitHCursor)
            elif self.zoom != 'fit' and self.mode == 'image':
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            return
        kind, start, origin, extra = self._drag
        if kind == 'split':
            self.split = min(.98, max(.02, pos.x() / max(1, self.width())))
            self.update()
        elif kind == 'pan':
            disp = self._display_rect()
            dx = (pos.x() - start.x()) / disp.width()
            dy = (pos.y() - start.y()) / disp.height()
            self.center = QPointF(origin.x() - dx, origin.y() - dy)
            self._clamp_center()
            self.update()
            self.roi_timer.start()
        elif kind == 'crop_move':
            img_rect, _ = self._crop_rects()
            dx = (pos.x() - start.x()) / img_rect.width()
            dy = (pos.y() - start.y()) / img_rect.height()
            x0, y0, x1, y1 = origin
            w, h = x1 - x0, y1 - y0
            nx0 = min(1 - w, max(0, x0 + dx))
            ny0 = min(1 - h, max(0, y0 + dy))
            self.crop['rect'] = [nx0, ny0, nx0 + w, ny0 + h]
            self.update()
        elif kind == 'crop_corner':
            img_rect, _ = self._crop_rects()
            x0, y0, x1, y1 = origin
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            anchor = {0: (x1, y1), 1: (x0, y1), 2: (x1, y0), 3: (x0, y0)}[extra]
            px = (pos.x() - img_rect.left()) / img_rect.width()
            py = (pos.y() - img_rect.top()) / img_rect.height()
            aspect = img_rect.width() / img_rect.height()
            ratio = self.crop['ratio'] / aspect             # normalised width/height ratio
            w = max(abs(px - anchor[0]), abs(py - anchor[1]) * ratio)
            h = w / ratio
            max_w = min(1, 1 * ratio)
            w = min(max(.05, w), max_w)
            h = w / ratio
            if h > 1:
                h, w = 1, ratio
            sx = -1 if extra in (0, 2) else 1
            sy = -1 if extra in (0, 1) else 1
            nx0 = anchor[0] if sx > 0 else anchor[0] - w
            ny0 = anchor[1] if sy > 0 else anchor[1] - h
            nx0 = min(1 - w, max(0, nx0))
            ny0 = min(1 - h, max(0, ny0))
            self.crop['rect'] = [nx0, ny0, nx0 + w, ny0 + h]
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag and self._drag[0].startswith('crop'):
            self._emit_crop()
        if self._drag and self._drag[0] == 'split':
            self.compareMoved.emit(self.split)
        self._drag = None
        self.mouseMoveEvent(e)

    def _emit_crop(self):
        x0, y0, x1, y1 = self.crop['rect']
        img = self.crop['image']
        aspect = img.width() / img.height()
        ratio = self.crop['ratio']
        full_w = min(1, ratio / aspect)          # width of an unzoomed crop, normalised
        zoom = max(1, min(8, full_w / max(1e-6, x1 - x0)))
        w, h = x1 - x0, y1 - y0
        cx = (x0 + w / 2) if w < 1 - 1e-6 else .5
        cy = (y0 + h / 2) if h < 1 - 1e-6 else .5
        self.cropEdited.emit(cx, cy, zoom)

    def mouseDoubleClickEvent(self, e):
        if self.mode != 'image' or self._near_split(e.position()):
            return
        self.set_zoom(1.0 if self.zoom == 'fit' else 'fit', e.position())

    def wheelEvent(self, e):
        if self.mode == 'crop' and self.crop:
            steps = e.angleDelta().y() / 120
            x0, y0, x1, y1 = self.crop['rect']
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            img = self.crop['image']
            aspect = img.width() / img.height()
            ratio = self.crop['ratio'] / aspect
            w = min(min(1, ratio), max(.05, (x1 - x0) * (0.9 ** steps)))
            h = w / ratio
            if h > 1:
                h, w = 1, ratio
            nx0 = min(1 - w, max(0, cx - w / 2))
            ny0 = min(1 - h, max(0, cy - h / 2))
            self.crop['rect'] = [nx0, ny0, nx0 + w, ny0 + h]
            self.update()
            self._emit_crop()
            return
        if self.mode != 'image':
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            levels = ['fit', 1.0, 2.0]
            idx = levels.index(self.zoom) if self.zoom in levels else 0
            idx = min(2, max(0, idx + (1 if e.angleDelta().y() > 0 else -1)))
            self.set_zoom(levels[idx], e.position())
        elif self.zoom != 'fit':
            disp = self._display_rect()
            dy = -e.angleDelta().y() / disp.height()
            dx = -e.angleDelta().x() / disp.width()
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                dx, dy = dy, 0
            self.center = QPointF(self.center.x() + dx, self.center.y() + dy)
            self._clamp_center()
            self.update()
            self.roi_timer.start()
        else:
            e.ignore()

    def _request_roi(self):
        region = self.visible_region()
        if region is None:
            return
        if self.roi_region and self.roi_img is not None:
            x, y, w, h = self.roi_region
            rx, ry, rw, rh = region
            if rx >= x and ry >= y and rx + rw <= x + w and ry + rh <= y + h:
                return
        x, y, w, h = region
        mx, my = int(w * .15), int(h * .15)
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(self.canvas[0], x + w + mx), min(self.canvas[1], y + h + my)
        self.roiRequested.emit((x0, y0, x1 - x0, y1 - y0))
