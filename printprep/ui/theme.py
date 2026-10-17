"""Design tokens and the application style sheet.

Neutral greys around photos (no tinted chrome that biases colour judgement, cf. ISO
12646). Blue marks interaction and selection; each inspector area has its own accent
(size — blue, light — amber, detail — teal, style — pink, neural — violet, output —
green) used only on small icon chips, so the eye finds sections instantly without
colouring the area around the image.
"""
from PySide6.QtGui import QColor, QFont, QPalette

DARK = dict(
    name='dark',
    bg='#111214', panel='#18191c', raised='#202125', hover='#292a2f', press='#313238',
    border='#2a2b30', border_strong='#3a3c43', text='#eeeef1', text2='#aeb1ba', text3='#757984',
    accent='#3d8bfd', accent_hover='#5b9dff', accent_press='#2f78e6', accent_soft='rgba(61,139,253,0.16)',
    accent_text='#ffffff', success='#34c77b', warning='#f5a524', danger='#ff5d5d',
    viewer_dark='#0c0d0f', viewer_gray='#767676', viewer_light='#d6d6d6',
    track='#3a3c43', track_fill_off='#4a4d55', knob='#f4f5f7', knob_off='#6b6e76', seg_checked='#3a3d45',
    hist_bg='#0d0e10', skeleton='#1d1e22', disabled='#50535b', primary_off_bg='#2a3a58', primary_off_fg='#8ea3c8',
    scroll='#3a3c43', scroll_hover='#4b4e57', input_hover='#50535c', drop_active='#1b2333',
    chip_accent='#8fb6ff', chip_warning='#f5c475', chip_success='#6fdca8', chip_danger='#ff9a9a', chip_neural='#c9b1ff',
    on_accent_soft='#cfe0ff',
)
LIGHT = dict(
    name='light',
    bg='#eceef2', panel='#f8f9fb', raised='#ffffff', hover='#eef0f4', press='#e2e5eb',
    border='#dfe2e8', border_strong='#cbd0d9', text='#15171c', text2='#4a505d', text3='#7b8190',
    accent='#2f6fe4', accent_hover='#2462d3', accent_press='#1d55bd', accent_soft='rgba(47,111,228,0.12)',
    accent_text='#ffffff', success='#178a52', warning='#b86e00', danger='#d43c3c',
    viewer_dark='#16171a', viewer_gray='#767676', viewer_light='#d9dadc',
    track='#d4d8df', track_fill_off='#b9bec8', knob='#ffffff', knob_off='#c9cdd5', seg_checked='#ffffff',
    hist_bg='#f2f3f6', skeleton='#dcdfe5', disabled='#a7acb6', primary_off_bg='#b8cdf3', primary_off_fg='#eef3fd',
    scroll='#c5cad3', scroll_hover='#aab0bb', input_hover='#b3b9c4', drop_active='#e3ecfd',
    chip_accent='#1f5cc8', chip_warning='#8a5300', chip_success='#11703f', chip_danger='#b52f2f', chip_neural='#6a3fd1',
    on_accent_soft='#1d4fb0',
)
T = dict(DARK)
ACCENTS = dict(size='#3d8bfd', light='#f5a524', detail='#22c3a6', style='#e45fae', neural='#9b6bff',
               output='#34c77b', photo='#5b9dff', preset='#3d8bfd')


def resolve(name):
    """'system' follows Windows' app colour mode."""
    if name in ('dark', 'light'):
        return name
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        return 'light' if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light else 'dark'
    except Exception:
        return 'dark'


def apply_theme(name):
    """Switch tokens in place; widgets read them when they are built."""
    T.clear()
    T.update(LIGHT if resolve(name) == 'light' else DARK)
    return T['name']
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
QPushButton#Primary:disabled { background: %(primary_off_bg)s; border-color: %(primary_off_bg)s; color: %(primary_off_fg)s; }
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
QToolButton:disabled { color: %(disabled)s; }
QToolButton::menu-indicator { image: none; width: 0; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %(raised)s; border: 1px solid %(border_strong)s; border-radius: 7px;
    padding: 5px 8px; min-height: 20px; color: %(text)s; selection-background-color: %(accent)s;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: %(input_hover)s; }
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
QPushButton#Dropdown:hover { border-color: %(input_hover)s; background: %(hover)s; }
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
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 3px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(scroll)s; border-radius: 3px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: %(scroll_hover)s; }
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
