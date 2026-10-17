"""Horizontal filmstrip with async thumbnails, skeleton placeholders and badges."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from . import icons
from .theme import T
from ..i18n import tr

THUMB_H = 84
ITEM_W = 118
ITEM_H = 112


class StripModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.photos = []
        self.thumbs = {}
        self.badges = {}          # path -> dict(edited=bool, warning=str)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.photos)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        photo = self.photos[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return photo.path.name
        if role == Qt.ItemDataRole.ToolTipRole:
            badge = self.badges.get(str(photo.path), {})
            lines = [photo.path.name, tr('{v} × {v2} px · {megapixels:.1f} Мп · {bits} бит', v=photo.size[0], v2=photo.size[1], megapixels=photo.megapixels, bits=photo.bits),
                     photo.profile]
            if badge.get('edited'):
                lines.append(tr('Есть правки этого снимка'))
            if badge.get('warning'):
                lines.append(tr('Внимание: ') + badge['warning'])
            return '\n'.join(lines)
        if role == Qt.ItemDataRole.UserRole:
            return photo
        return None

    def set_photos(self, photos):
        self.beginResetModel()
        self.photos = list(photos)
        self.thumbs = {}
        self.badges = {}
        self.endResetModel()

    def set_thumb(self, path, image):
        self.thumbs[path] = image
        for row, p in enumerate(self.photos):
            if str(p.path) == path:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx)
                break

    def set_badges(self, badges):
        self.badges = badges
        if self.photos:
            self.dataChanged.emit(self.index(0), self.index(len(self.photos) - 1))

    def loading(self):
        return len(self.thumbs) < len(self.photos)


class StripDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        return QSize(ITEM_W, ITEM_H)

    def paint(self, p, option, index):
        model = index.model()
        photo = model.photos[index.row()]
        path = str(photo.path)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        current = self.view.currentIndex() == index
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        box = QRectF(r.left(), r.top(), r.width(), THUMB_H)
        if hover and not current:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T['hover']))
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 9, 9)
        image = model.thumbs.get(path)
        clip = QPainterPath()
        if image is not None and not image.isNull():
            k = min(box.width() / image.width(), box.height() / image.height())
            w, h = image.width() * k, image.height() * k
            target = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
            clip.addRoundedRect(target, 5, 5)
            p.setClipPath(clip)
            p.drawImage(target, image)
            p.setClipping(False)
            frame = target
        else:
            aspect = photo.size[0] / max(1, photo.size[1])
            w = min(box.width(), box.height() * aspect)
            h = w / aspect
            frame = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            phase = (self.view.phase % 60) / 60
            base = QColor(T['skeleton'])
            lift = int(10 * abs(phase - .5) * 2) * (1 if T['name'] == 'dark' else -1)
            p.setBrush(QColor(min(255, max(0, base.red() + lift)), min(255, max(0, base.green() + lift)), min(255, max(0, base.blue() + lift))))
            p.drawRoundedRect(frame, 5, 5)
        if current or selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T['accent'] if current else '#7aa7ff'), 2.5 if current else 1.5))
            p.drawRoundedRect(frame.adjusted(-2.5, -2.5, 2.5, 2.5), 7, 7)
        badge = model.badges.get(path, {})
        x = frame.right() - 4
        if badge.get('edited'):
            x -= 18
            c = QRectF(x, frame.top() + 4, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 21, 24, 220))
            p.drawEllipse(c)
            p.drawPixmap(c.adjusted(3, 3, -3, -3).toRect(), icons.pixmap('edit', T['accent_hover'], 12))
        if badge.get('warning'):
            c = QRectF(frame.left() + 4, frame.bottom() - 22, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 21, 24, 220))
            p.drawEllipse(c)
            p.drawPixmap(c.adjusted(3, 3, -3, -3).toRect(), icons.pixmap('warning', T['warning'], 12))
        f = QFont(option.font)
        f.setPointSizeF(8.25)
        p.setFont(f)
        p.setPen(QColor(T['text'] if current else T['text2']))
        name = p.fontMetrics().elidedText(photo.path.name, Qt.TextElideMode.ElideMiddle, int(r.width()))
        p.drawText(QRectF(r.left(), box.bottom() + 4, r.width(), 16), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, name)
        p.restore()


class Filmstrip(QListView):
    currentPhotoChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = StripModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(StripDelegate(self))
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.setFixedHeight(ITEM_H + 16)
        self.setSpacing(0)
        self.setAccessibleName(tr('Лента снимков'))
        self.phase = 0
        self.shimmer = QTimer(self)
        self.shimmer.setInterval(40)
        self.shimmer.timeout.connect(self._tick)
        self.selectionModel().currentChanged.connect(lambda cur, _: self.currentPhotoChanged.emit(cur.row()))

    def _tick(self):
        self.phase += 1
        if not self.model_.loading():
            self.shimmer.stop()
        self.viewport().update()

    def set_photos(self, photos):
        self.model_.set_photos(photos)
        self.shimmer.start()

    def set_thumb(self, path, image):
        self.model_.set_thumb(path, image)

    def set_badges(self, badges):
        self.model_.set_badges(badges)

    def select_row(self, row):
        if 0 <= row < self.model_.rowCount():
            idx = self.model_.index(row)
            self.setCurrentIndex(idx)
            self.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def selected_rows(self):
        return sorted(i.row() for i in self.selectionModel().selectedIndexes())

    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        delta = e.angleDelta().y() or e.angleDelta().x()
        bar.setValue(bar.value() - delta)
        e.accept()
