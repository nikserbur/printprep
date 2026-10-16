"""Predictable form controls and pixel-aware image viewing."""
from PIL import Image
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox as QtComboBox, QSpinBox as QtSpinBox,
    QDoubleSpinBox as QtDoubleSpinBox, QScrollArea, QLabel, QListView,
    QAbstractItemView, QAbstractSpinBox, QFrame, QSizePolicy)


def to_qimage(im):
    rgb = im.convert('RGB')
    return QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()


class Choice(QtComboBox):
    def __init__(self, *args):
        super().__init__(*args)
        view = QListView()
        view.setUniformItemSizes(True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setView(view)
        self.setMaxVisibleItems(10)
        self.setMinimumContentsLength(8)
        self.setSizeAdjustPolicy(QtComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def wheelEvent(self, event):
        # Scrolling a form must not accidentally select another preset.
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class ValueSpin(QtSpinBox):
    def __init__(self, *args):
        super().__init__(*args)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)

    def wheelEvent(self, event):
        event.ignore()


class DecimalSpin(QtDoubleSpinBox):
    def __init__(self, *args):
        super().__init__(*args)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)

    def wheelEvent(self, event):
        event.ignore()


class PhotoView(QScrollArea):
    """Fit view has no bars; 100% maps one image pixel to one display pixel."""
    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 180)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidgetResizable(False)
        self.setStyleSheet('QScrollArea { background: #171d22; border-radius: 10px; }')
        self.viewport().setStyleSheet('background: #171d22;')
        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setStyleSheet('background: transparent; color: #9aa6ac;')
        self.canvas.setText('Выберите фотографию')
        self.canvas.resize(240, 180)
        self.setWidget(self.canvas)
        self.picture = None
        self.image = None
        self.zoom_mode = 'fit'

    def set_image(self, im):
        self.image = im
        self.picture = QPixmap.fromImage(to_qimage(im))
        self.update_picture()

    def set_zoom(self, mode):
        self.zoom_mode = mode
        self.update_picture()

    def update_picture(self):
        if self.picture is None:
            return
        dpr = self.devicePixelRatioF()
        if self.zoom_mode == 'fit':
            available = self.viewport().size() - QSize(24, 24)
            factor = min(max(1, available.width()) * dpr / self.picture.width(),
                         max(1, available.height()) * dpr / self.picture.height())
        else:
            factor = float(self.zoom_mode)
        target = QSize(max(1, round(self.picture.width() * factor)), max(1, round(self.picture.height() * factor)))
        pix = self.picture.scaled(target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        self.canvas.setPixmap(pix)
        self.canvas.resize(max(1, round(pix.width() / dpr)), max(1, round(pix.height() / dpr)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_picture()


from PySide6.QtWidgets import QStackedWidget


class HeightStack(QStackedWidget):
    """Only the visible size form contributes to layout height."""
    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()
