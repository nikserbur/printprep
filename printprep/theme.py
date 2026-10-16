"""Shared desktop palette and visual hierarchy."""
from pathlib import Path

STYLE = '''
QWidget { color: #202d2a; font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; }
QMainWindow, QDialog, QWidget#shell { background: #f5f6f2; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 22px; font-weight: 700; letter-spacing: -0.7px; }
QLabel#hero { font-size: 38px; font-weight: 700; letter-spacing: -1.5px; }
QLabel#title { font-size: 25px; font-weight: 650; letter-spacing: -0.6px; }
QLabel#muted { color: #74817b; }
QLabel#eyebrow { font-size: 11px; font-weight: 700; color: #738079; letter-spacing: 1.5px; }
QLabel#tag { color: #357461; background: #e5f0e9; padding: 6px 12px; border-radius: 13px; font-size: 11px; font-weight: 600; }
QLabel#metric { font-size: 27px; font-weight: 650; }
QFrame#card, QWidget#card { background: #ffffff; border: 1px solid #e2e7df; border-radius: 16px; }
QFrame#dropzone { background: #ffffff; border: 2px dashed #cbd7cb; border-radius: 22px; }
QFrame#header, QFrame#actionbar { background: #ffffff; border: none; }
QFrame#rail { background: #edf0e9; border: none; }
QPushButton { background: #ffffff; color: #33463d; border: 1px solid #dce3d9; border-radius: 9px; padding: 10px 16px; font-weight: 600; min-height: 18px; }
QPushButton:hover { background: #f0f5ed; border-color: #9eb5a4; }
QPushButton:pressed { background: #e5eee1; }
QPushButton:focus { border: 2px solid #7caa8e; }
QPushButton:disabled { color: #a4ada5; background: #f0f2ee; border-color: #e8ece5; }
QPushButton#primary { background: #245e45; color: #ffffff; border: 1px solid #245e45; padding: 13px 23px; }
QPushButton#primary:hover { background: #174b35; }
QPushButton#primary:disabled { background: #c8d9cb; border-color: #c8d9cb; color: #f5f8f4; }
QPushButton#quiet { background: transparent; border-color: transparent; color: #677a6f; }
QPushButton#quiet:hover { background: #e9eee5; }
QPushButton#presetCard { min-height: 104px; max-height: 104px; background: #ffffff; border: 1px solid #dfe6db; border-radius: 13px; text-align: left; padding: 0; }
QPushButton#presetCard:checked { background: #eff6eb; border: 2px solid #528466; }
QPushButton#presetCard:hover { background: #f5f9f0; border-color: #8aa68d; }
QPushButton#presetCard QLabel#cardTitle { font-size: 16px; font-weight: 650; color: #263b2f; }
QPushButton#presetCard QLabel#cardNote { color: #758475; font-size: 12px; }
QGroupBox { background: #ffffff; border: 1px solid #e1e7dd; border-radius: 12px; margin-top: 16px; padding: 19px 14px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 13px; padding: 0 6px; color: #607163; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #dce3d8; border-radius: 7px; padding: 7px; min-height: 22px; color: #263e30; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #73a184; }
QComboBox QAbstractItemView { background: #ffffff; color: #263e30; selection-background-color: #e4efde; selection-color: #204c32; padding: 4px; }
QListWidget { background: #ffffff; border: 1px solid #e0e6dc; border-radius: 12px; padding: 5px; outline: none; }
QListWidget::item { border: 1px solid transparent; border-radius: 7px; padding: 10px; margin: 2px; }
QListWidget::item:selected { background: #edf4e6; border-color: #94b18a; color: #233e2a; }
QListWidget::item:hover { background: #f1f5ed; }
QScrollArea { background: transparent; border: none; }
QCheckBox { spacing: 8px; font-weight: 400; background: transparent; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #b8c5b5; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:checked { background: #528466; border: 3px solid #c0d4b9; }
QProgressBar { border: none; background: #e4eadf; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #528466; border-radius: 5px; }
QSlider::groove:horizontal { height: 5px; background: #dbe5d4; border-radius: 2px; }
QSlider::handle:horizontal { background: #528466; width: 14px; margin: -5px 0; border-radius: 7px; }
QToolTip { background: #253f2d; color: #ffffff; border: none; padding: 8px; }
QSplitter::handle { background: #f5f6f2; width: 12px; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #ccd6c6; min-height: 32px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QAbstractScrollArea::corner { background: transparent; }
'''

_CHEVRON = (Path(__file__).resolve().parents[1] / 'assets' / 'chevron.png').as_posix()
STYLE += "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; }"
STYLE += f'QComboBox::down-arrow {{ image: url("{_CHEVRON}"); width: 12px; height: 8px; }}'
STYLE += "QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button { width: 18px; border: none; background: transparent; }"
