"""Design tokens and the application style sheet.

Neutral greys around photos (no tinted chrome that biases colour judgement, cf. ISO
12646). Blue marks interaction and selection; each inspector area has its own accent
(size — blue, light — amber, detail — teal, style — pink, neural — violet, output —
green) used only on small icon chips, so the eye finds sections instantly without
colouring the area around the image.
"""
from PySide6.QtGui import QColor, QFont, QPalette

T = dict(
    bg='#111214', panel='#18191c', raised='#202125', hover='#292a2f', press='#313238',
    border='#2a2b30', border_strong='#3a3c43', text='#eeeef1', text2='#aeb1ba', text3='#757984',
    accent='#3d8bfd', accent_hover='#5b9dff', accent_press='#2f78e6', accent_soft='rgba(61,139,253,0.16)',
    accent_text='#ffffff', success='#34c77b', warning='#f5a524', danger='#ff5d5d',
    viewer_dark='#0c0d0f', viewer_gray='#767676', viewer_light='#d6d6d6',
)
ACCENTS = dict(size='#3d8bfd', light='#f5a524', detail='#22c3a6', style='#e45fae', neural='#9b6bff',
               output='#34c77b', photo='#5b9dff', preset='#3d8bfd')
RADIUS = 8
FONT_FAMILY = 'Segoe UI Variable Text'


def color(name, alpha=None):
    c = QColor(T[name]) if not T[name].startswith('rgba') else QColor(61, 139, 253, 41)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def rgba(hex_color, alpha):
    c = QColor(hex_color)
    return f'rgba({c.red()},{c.green()},{c.blue()},{alpha})'


def app_font():
    font = QFont(FONT_FAMILY)
    if not font.exactMatch():
        font = QFont('Segoe UI')
    font.setPointSizeF(9.75)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def palette():
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: T['bg'], QPalette.ColorRole.WindowText: T['text'],
        QPalette.ColorRole.Base: T['raised'], QPalette.ColorRole.AlternateBase: T['panel'],
        QPalette.ColorRole.Text: T['text'], QPalette.ColorRole.Button: T['raised'],
        QPalette.ColorRole.ButtonText: T['text'], QPalette.ColorRole.Highlight: T['accent'],
        QPalette.ColorRole.HighlightedText: '#ffffff', QPalette.ColorRole.ToolTipBase: T['raised'],
        QPalette.ColorRole.ToolTipText: T['text'], QPalette.ColorRole.PlaceholderText: T['text3'],
        QPalette.ColorRole.Link: T['accent'], QPalette.ColorRole.Mid: T['border'],
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(T['text3']))
    return p


STYLE = '''
* { outline: none; }
QWidget { color: %(text)s; background: transparent; }
QMainWindow, QDialog, #Window { background: %(bg)s; }
#TopBar { background: %(panel)s; border-bottom: 1px solid %(border)s; }
#Panel, #LeftPanel, #RightPanel { background: %(panel)s; }
#LeftPanel { border-right: 1px solid %(border)s; }
#RightPanel { border-left: 1px solid %(border)s; }
#Strip { background: %(panel)s; border-top: 1px solid %(border)s; }
#ViewerBar { background: %(bg)s; }
#Card { background: %(raised)s; border: 1px solid %(border)s; border-radius: 10px; }
#Hint { color: %(text3)s; }
#Muted { color: %(text2)s; }
#Title { font-size: 15px; font-weight: 600; }
#Brand { font-size: 15px; font-weight: 700; letter-spacing: 0.2px; }
#Eyebrow { color: %(text3)s; font-size: 11px; font-weight: 600; letter-spacing: 0.8px; }
#Big { font-size: 22px; font-weight: 600; }

QPushButton {
    background: %(raised)s; color: %(text)s; border: 1px solid %(border_strong)s;
    border-radius: 8px; padding: 6px 14px; min-height: 20px; font-weight: 500;
}
QPushButton:hover { background: %(hover)s; }
QPushButton:pressed { background: %(press)s; }
QPushButton:disabled { color: %(text3)s; background: %(panel)s; border-color: %(border)s; }
QPushButton:focus { border-color: %(accent)s; }
QPushButton#Primary { background: %(accent)s; border: 1px solid %(accent)s; color: #ffffff; font-weight: 600; padding: 7px 18px; }
QPushButton#Primary:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton#Primary:pressed { background: %(accent_press)s; }
QPushButton#Primary:disabled { background: #2a3a58; border-color: #2a3a58; color: #8ea3c8; }
QPushButton#Ghost { background: transparent; border-color: transparent; color: %(text2)s; }
QPushButton#Ghost:hover { background: %(hover)s; color: %(text)s; }
QPushButton#Danger { color: %(danger)s; }
QPushButton#Danger:disabled { color: %(text3)s; }
QPushButton#Link { background: transparent; border: none; color: %(accent)s; padding: 2px 4px; }
QPushButton#Link:hover { color: %(accent_hover)s; text-decoration: underline; }

QToolButton { background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 5px; color: %(text2)s; }
QToolButton:hover { background: %(hover)s; color: %(text)s; }
QToolButton:pressed { background: %(press)s; }
QToolButton:checked { background: %(accent_soft)s; color: %(accent_hover)s; border-color: transparent; }
QToolButton:disabled { color: #50535b; }
QToolButton::menu-indicator { image: none; width: 0; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %(raised)s; border: 1px solid %(border_strong)s; border-radius: 7px;
    padding: 5px 8px; min-height: 20px; color: %(text)s; selection-background-color: %(accent)s;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: #50535c; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QComboBox:on { border-color: %(accent)s; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: %(text3)s; background: %(panel)s; border-color: %(border)s; }
QSpinBox, QDoubleSpinBox { padding: 5px 2px 5px 8px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; background: transparent; margin: 2px 2px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; background: transparent; margin: 0 2px 2px 0; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: %(hover)s; border-radius: 4px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(%(chevron_up)s); width: 8px; height: 8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(%(chevron)s); width: 8px; height: 8px; }
QComboBox { padding-right: 26px; combobox-popup: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url(%(chevron)s); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: %(raised)s; border: 1px solid %(border_strong)s; border-radius: 8px; padding: 4px;
    selection-background-color: %(accent_soft)s; selection-color: %(text)s; outline: none;
}
QComboBox QAbstractItemView::item { min-height: 28px; padding: 4px 10px; border-radius: 6px; }
QComboBox QAbstractItemView::item:hover { background: %(hover)s; }

QPushButton#Dropdown { text-align: left; padding: 5px 30px 5px 10px; background: %(raised)s; border: 1px solid %(border_strong)s;
    border-radius: 7px; font-weight: 400; min-height: 20px; }
QPushButton#Dropdown:hover { border-color: #50535c; background: %(hover)s; }
QPushButton#Dropdown:focus { border-color: %(accent)s; }
QMenu { background: %(raised)s; border: 1px solid %(border_strong)s; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 30px; border-radius: 6px; color: %(text)s; }
QMenu::item:selected { background: %(accent_soft)s; }
QMenu::item:checked { color: %(accent_hover)s; font-weight: 600; }
QMenu::indicator { width: 14px; height: 14px; left: 9px; }
QMenu::indicator:checked { image: url(%(check_accent)s); }
QMenu::item:disabled { color: %(text3)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 5px 8px; }
QMenu::icon { padding-left: 8px; }

QToolTip { background: %(raised)s; color: %(text)s; border: 1px solid %(border_strong)s; border-radius: 6px; padding: 6px 8px; }

QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a3c43; border-radius: 3px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: #4b4e57; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3a3c43; border-radius: 3px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: #4b4e57; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QListView, QListWidget { background: transparent; border: none; }
QSplitter::handle { background: %(border)s; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QProgressBar { background: %(hover)s; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: %(accent)s; border-radius: 3px; }
QDialog QLabel { background: transparent; }
QMessageBox { background: %(panel)s; }
QMessageBox QLabel { color: %(text)s; }
QCheckBox { spacing: 8px; color: %(text)s; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid %(border_strong)s; background: %(raised)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: url(%(check)s); }
QInputDialog QLineEdit { min-width: 320px; }
'''


def stylesheet(chevron_path, check_path, chevron_up_path, check_accent_path):
    return STYLE % dict(T, chevron=chevron_path, check=check_path, chevron_up=chevron_up_path, check_accent=check_accent_path)
