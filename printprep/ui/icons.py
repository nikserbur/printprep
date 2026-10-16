"""Small stroke icon set (original drawings, 24×24 grid), tinted at runtime."""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    'folder': '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    'folder_open': '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h6.5A2.5 2.5 0 0 1 20 9.5V10"/><path d="M3.5 19 6 11.8A1.5 1.5 0 0 1 7.4 10.8H21l-2.7 7.3a1.5 1.5 0 0 1-1.4 1H5a1.5 1.5 0 0 1-1.5-1.1z"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'undo': '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    'redo': '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    'help': '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.3a2.6 2.6 0 0 1 5 1c0 1.8-2.5 2.2-2.5 3.7"/><path d="M12 17.2h.01"/>',
    'crop': '<path d="M6 2.5V16a2 2 0 0 0 2 2h13.5"/><path d="M2.5 6H16a2 2 0 0 1 2 2v13.5"/>',
    'rotate_left': '<path d="M3.5 12A8.5 8.5 0 1 0 6 6"/><path d="M3 3.5V8h4.5"/>',
    'rotate_right': '<path d="M20.5 12A8.5 8.5 0 1 1 18 6"/><path d="M21 3.5V8h-4.5"/>',
    'compare': '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M12 2.5v19"/><path d="M15 9.5l2 2.5-2 2.5"/><path d="M9 9.5 7 12l2 2.5"/>',
    'fit': '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    'sparkles': '<path d="M11 3.5 12.8 8 17.5 9.8 12.8 11.6 11 16.1 9.2 11.6 4.5 9.8 9.2 8z"/><path d="M18 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    'warning': '<path d="M10.3 4.2 2.6 17.6A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-2.9L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4.2M12 17h.01"/>',
    'check': '<path d="m5 12.5 4.5 4.5L19.5 7"/>',
    'close': '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    'more': '<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
    'chevron_down': '<path d="m6 9 6 6 6-6"/>',
    'chevron_right': '<path d="m9 6 6 6-6 6"/>',
    'chevron_up': '<path d="m6 15 6-6 6 6"/>',
    'chevron_left': '<path d="m15 6-6 6 6 6"/>',
    'arrow_right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'save': '<path d="M5 3.5h11l3.5 3.5v12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V5A1.5 1.5 0 0 1 5 3.5z"/><path d="M7.5 3.5v5h8v-5M7.5 20.5v-6h9v6"/>',
    'reset': '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.5h4.5"/>',
    'image': '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="9.5" r="1.6"/><path d="m4 17 5-5 4 4 2.5-2.5L20 18"/>',
    'safe': '<rect x="3" y="4" width="18" height="16" rx="1.5"/><rect x="6.5" y="7.5" width="11" height="9" rx=".5" stroke-dasharray="2 2"/>',
    'eye': '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
    'trash': '<path d="M4.5 6.5h15M9.5 6.5V4.5h5v2M6.5 6.5l1 13h9l1-13M10 10.5v6M14 10.5v6"/>',
    'edit': '<path d="M15.5 4.5 19.5 8.5 9 19H5v-4z"/><path d="m13.5 6.5 4 4"/>',
    'copy': '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    'layers': '<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="m3 12 9 4.5 9-4.5"/><path d="m3 16 9 4.5 9-4.5"/>',
    'sliders': '<path d="M5 20v-6M5 10V4M12 20v-9M12 7V4M19 20v-4M19 12V4"/><path d="M3 14h4M10 7h4M17 16h4"/>',
    'cpu': '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx=".5"/><path d="M9.5 2.5V6M14.5 2.5V6M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    'palette': '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-1.3-1.1-1.6-1.1-2.7 0-1 .8-1.6 1.8-1.6H17a3.5 3.5 0 0 0 3.5-3.5c0-4.2-3.8-7.5-8.5-7.5z"/><circle cx="7.8" cy="11" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>',
    'file': '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5M9 13h6M9 16.5h4"/>',
    'printer': '<path d="M7 8.5V3.5h10v5"/><rect x="3.5" y="8.5" width="17" height="8" rx="2"/><path d="M7 14h10v6.5H7z"/>',
    'swap': '<path d="M7 20V4M3.5 7.5 7 4l3.5 3.5M17 4v16M13.5 16.5 17 20l3.5-3.5"/>',
    'stop': '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    'contrast': '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17a8.5 8.5 0 0 0 0-17z" fill="currentColor"/>',
    'detail': '<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4.8-4.8M8.5 11h5M11 8.5v5"/>',
    'wand': '<path d="m4 20 11-11M14 5l1-2 1 2 2 1-2 1-1 2-1-2-2-1zM19 11l.6 1.4L21 13l-1.4.6L19 15l-.6-1.4L17 13l1.4-.6z"/><path d="m13 7 4 4"/>',
    'star': '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.6l1-5.8L3.5 9.7l5.9-.9z"/>',
    'grid': '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17"/>',
    'level': '<path d="M3 15.5 21 8.5"/><circle cx="12" cy="12" r="1.5"/><path d="M3 19.5h18"/>',
    'upload': '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4.5 15v3A2.5 2.5 0 0 0 7 20.5h10a2.5 2.5 0 0 0 2.5-2.5v-3"/>',
    'download': '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4.5 15v3A2.5 2.5 0 0 0 7 20.5h10a2.5 2.5 0 0 0 2.5-2.5v-3"/>',
    'dot': '<circle cx="12" cy="12" r="4" fill="currentColor"/>',
}


def svg(name, color='#e9eaee', width=1.8):
    body = PATHS[name].replace('currentColor', color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def pixmap(name, color='#e9eaee', size=18, dpr=2.0, width=1.8):
    renderer = QSvgRenderer(QByteArray(svg(name, color, width).encode()))
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color='#b0b3bc', active='#e9eaee', checked='#669eff', size=18):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, active, size), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(name, checked, size), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, checked, size), QIcon.Mode.Active, QIcon.State.On)
    ic.addPixmap(pixmap(name, '#50535b', size), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def write_svg(path, name, color, width=2.2):
    path.write_text(svg(name, color, width), encoding='utf-8')
    return path.as_posix()
