"""Advanced neural settings. The defaults are the measured best, so most people never open it."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from . import icons
from .controls import ParamSlider, button, hline, label
from .theme import ACCENTS
from ..i18n import tr

DEFAULT_STRENGTH = 100
DEFAULT_DETAIL = 100


class NeuralDialog(QDialog):
    changed = Signal(str, float, bool)       # key, value, commit

    def __init__(self, strength, detail, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Нейросеть · дополнительно'))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap('cpu', ACCENTS['neural'], 26))
        head.addWidget(ic)
        head.addWidget(label(tr('Тонкая настройка нейросети'), 'Title'), 1)
        lay.addLayout(head)
        lay.addWidget(label(tr('Значения по умолчанию подобраны замером на эталонных снимках: лучшая точность и '
                            'сохранение фактуры. Менять их нужно только если результат не нравится.'), 'Muted', wrap=True))
        lay.addWidget(hline())
        self.strength = ParamSlider(tr('Сила'), 0, 100, 1, DEFAULT_STRENGTH, '%')
        self.strength.setValue(strength)
        self.strength.setToolTip(tr('Доля результата нейросети. Меньше — ближе к обычному увеличению.\n'
                                 'Меняется мгновенно, без пересчёта.'))
        lay.addWidget(self.strength)
        self.detail = ParamSlider(tr('Чистота  ←  →  Детали'), 0, 100, 1, DEFAULT_DETAIL, '')
        self.detail.setValue(detail)
        self.detail.setToolTip(tr('Влево — сильнее убирает шум и JPEG-артефакты, но может замылить фактуру.\n'
                               'Вправо — сохраняет зерно, траву, волосы и ткань.\n'
                               'После изменения снимок пересчитывается в фоне.'))
        lay.addWidget(self.detail)
        lay.addWidget(label(tr('«Детали» — это официальная регулировка шумоподавления Real-ESRGAN (смешивание двух '
                            'версий сети) плюс возврат мелкой фактуры исходника.'), 'Hint', wrap=True))
        for key, slider in (('neural_strength', self.strength), ('neural_detail', self.detail)):
            slider.valueChanged.connect(lambda v, k=key: self.changed.emit(k, v, False))
            slider.editingFinished.connect(lambda k=key, s=slider: self.changed.emit(k, s.value(), True))
        row = QHBoxLayout()
        row.addWidget(button(tr('По умолчанию'), self._defaults, 'Ghost', 'reset'))
        row.addStretch()
        row.addWidget(button(tr('Готово'), self.accept, 'Primary', 'check'))
        lay.addLayout(row)

    def _defaults(self):
        for key, slider, value in (('neural_strength', self.strength, DEFAULT_STRENGTH),
                                   ('neural_detail', self.detail, DEFAULT_DETAIL)):
            slider.setValue(value)
            self.changed.emit(key, value, True)
