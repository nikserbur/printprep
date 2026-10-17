"""Settings, per-photo edits, built-in presets and 1.x migration. No GUI or pixels here."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace
from .i18n import tr

MAX_PIXELS = 100_000_000
SIZE_MODES = ('original', 'print', 'pixels', 'long_edge')
FORMATS = ('JPEG', 'TIFF', 'PNG')
SHARPEN = ('off', 'screen', 'glossy', 'matte')
SHARPEN_AMOUNTS = ('low', 'standard', 'high')
NEURAL_MIN_SCALE = 1.3      # below this enlargement classic resampling looks the same in print
NEURAL_MAX_MP = 4.0         # larger sources rarely need it and cost too much on weak PCs

# Slider fields of Adjust: (title, low, high, step, unit). Order is the UI order.
ADJUST_RANGES = {
    'exposure': ('Экспозиция', -3.0, 3.0, .05, 'EV'),
    'contrast': ('Контраст', -100, 100, 1, ''),
    'highlights': ('Света', -100, 100, 1, ''),
    'shadows': ('Тени', -100, 100, 1, ''),
    'whites': ('Белые', -100, 100, 1, ''),
    'blacks': ('Чёрные', -100, 100, 1, ''),
    'temperature': ('Температура', -100, 100, 1, ''),
    'tint': ('Оттенок', -100, 100, 1, ''),
    'vibrance': ('Сочность', -100, 100, 1, ''),
    'saturation': ('Насыщенность', -100, 100, 1, ''),
    'clarity': ('Чёткость', -100, 100, 1, ''),
    'dehaze': ('Дымка', -100, 100, 1, ''),
    'denoise': ('Шумоподавление', 0, 100, 1, ''),
    'color_denoise': ('Цветовой шум', 0, 100, 1, ''),
}
NUMERIC_ADJUST = tuple(ADJUST_RANGES)

LOOKS = {
    'none': ('Нейтральный', {}),
    'vivid': ('Яркий', dict(vibrance=25, saturation=6, contrast=12, clarity=8)),
    'warm': ('Тёплый', dict(temperature=14, tint=3, vibrance=8)),
    'cool': ('Свежий', dict(temperature=-10, vibrance=6, clarity=4)),
    'portrait': ('Мягкий портрет', dict(contrast=-8, highlights=-18, shadows=12, clarity=-14, vibrance=6, saturation=-6, temperature=4)),
    'film': ('Плёнка', dict(contrast=10, saturation=-10, fade=10, split=1)),
    'matte': ('Матовый', dict(contrast=-12, saturation=-14, fade=18)),
    'bw': ('Ч/Б', dict(mono=1, contrast=8)),
    'bw_contrast': ('Ч/Б контрастный', dict(mono=1, contrast=30, clarity=16, blacks=-10)),
}


@dataclass
class Adjust:
    auto: bool = False
    auto_strength: float = 70
    auto_wb: bool = True
    auto_light: bool = True
    auto_color: bool = True
    auto_noise: bool = True
    exposure: float = 0.0
    contrast: float = 0
    highlights: float = 0
    shadows: float = 0
    whites: float = 0
    blacks: float = 0
    temperature: float = 0
    tint: float = 0
    vibrance: float = 0
    saturation: float = 0
    clarity: float = 0
    dehaze: float = 0
    denoise: float = 0
    color_denoise: float = 0
    look: str = 'none'
    look_strength: float = 100

    def validate(self):
        for key, (title, low, high, _, _) in ADJUST_RANGES.items():
            value = getattr(self, key)
            if not _finite(value) or not low <= value <= high:
                raise ValueError(tr('«{title}»: допустимо от {low:g} до {high:g}.', title=tr(title), low=low, high=high))
        if not _finite(self.auto_strength) or not 0 <= self.auto_strength <= 100:
            raise ValueError(tr('Сила авто-коррекции: от 0 до 100.'))
        if self.look not in LOOKS:
            raise ValueError(tr('Неизвестный стиль.'))
        if not _finite(self.look_strength) or not 0 <= self.look_strength <= 100:
            raise ValueError(tr('Сила стиля: от 0 до 100.'))

    def is_identity(self):
        return (not self.auto and self.look == 'none'
                and all(getattr(self, k) == 0 for k in NUMERIC_ADJUST))


@dataclass
class Settings:
    size_mode: str = 'original'
    width_mm: float = 102
    height_mm: float = 152
    dpi: int = 300
    pixel_width: int = 3840
    pixel_height: int = 2160
    long_edge: int = 3840
    fit: str = 'cover'
    auto_orientation: bool = True
    border_mm: float = 0
    background: str = '#ffffff'
    smart_crop: bool = True
    allow_upscale: bool = True
    format: str = 'JPEG'
    quality: int = 95
    bit_depth: int = 8
    output_space: str = 'sRGB'
    icc_path: str = ''
    intent: int = 1
    keep_exif: bool = True
    sharpen: str = 'off'
    sharpen_amount: str = 'standard'
    print_brightness: float = 0
    neural: bool = False
    neural_strength: float = 100
    neural_detail: float = 50           # 0 = cleanest, 100 = keep grain and fine texture
    adjust: Adjust = field(default_factory=Adjust)

    def validate(self, check_icc=True):
        if self.size_mode not in SIZE_MODES:
            raise ValueError(tr('Неизвестный режим размера.'))
        for value in (self.pixel_width, self.pixel_height, self.long_edge):
            if not isinstance(value, int) or isinstance(value, bool) or not 16 <= value <= 32768:
                raise ValueError(tr('Размер в пикселях: целое число от 16 до 32768.'))
        if not all(_finite(v) for v in (self.width_mm, self.height_mm, self.border_mm)):
            raise ValueError(tr('Размеры должны быть числами.'))
        if not (10 <= self.width_mm <= 2000 and 10 <= self.height_mm <= 2000):
            raise ValueError(tr('Сторона отпечатка: от 10 до 2000 мм.'))
        if not isinstance(self.dpi, int) or not 72 <= self.dpi <= 1200:
            raise ValueError(tr('PPI: от 72 до 1200.'))
        if self.size_mode == 'print':
            if self.border_mm < 0 or 2 * self.border_mm >= min(self.width_mm, self.height_mm):
                raise ValueError(tr('Поля должны оставлять место для фотографии.'))
        elif self.border_mm:
            raise ValueError(tr('Поля в миллиметрах доступны только для печатного размера.'))
        if self.fit not in ('cover', 'contain'):
            raise ValueError(tr('Неизвестный режим размещения.'))
        if self.format not in FORMATS:
            raise ValueError(tr('Неизвестный формат файла.'))
        if self.bit_depth not in (8, 16):
            raise ValueError(tr('Глубина цвета: 8 или 16 бит.'))
        if self.bit_depth == 16 and self.format == 'JPEG':
            raise ValueError(tr('JPEG бывает только 8-битным. Для 16 бит выберите TIFF или PNG.'))
        if not isinstance(self.quality, int) or not 50 <= self.quality <= 100:
            raise ValueError(tr('Качество JPEG: от 50 до 100.'))
        if self.output_space not in ('sRGB', 'ICC') or self.intent not in (0, 1, 2, 3):
            raise ValueError(tr('Неизвестные настройки цвета.'))
        if self.output_space == 'ICC':
            if self.bit_depth == 16:
                raise ValueError(tr('Преобразование в ICC принтера выполняется в 8 битах. Выберите 8 бит.'))
            if self.format == 'PNG':
                raise ValueError(tr('Для ICC принтера выберите JPEG или TIFF.'))
            if not self.icc_path:
                raise ValueError(tr('Выберите ICC-профиль принтера и бумаги.'))
            if check_icc:
                from PIL import ImageCms
                try:
                    profile = ImageCms.getOpenProfile(self.icc_path)
                except Exception as e:
                    raise ValueError(tr('ICC-профиль не читается: {e}', e=e)) from None
                if profile.profile.xcolor_space.strip() not in ('RGB', 'CMYK'):
                    raise ValueError(tr('Поддерживаются выходные ICC-профили RGB или CMYK.'))
        if self.sharpen not in SHARPEN or self.sharpen_amount not in SHARPEN_AMOUNTS:
            raise ValueError(tr('Неизвестный режим резкости.'))
        if not _finite(self.print_brightness) or not 0 <= self.print_brightness <= 40:
            raise ValueError(tr('Компенсация яркости отпечатка: от 0 до 40%.'))
        if type(self.neural) is not bool:
            raise ValueError(tr('Некорректный переключатель нейросети.'))
        if not _finite(self.neural_strength) or not 0 <= self.neural_strength <= 100:
            raise ValueError(tr('Сила нейросети: от 0 до 100.'))
        if not _finite(self.neural_detail) or not 0 <= self.neural_detail <= 100:
            raise ValueError(tr('Детализация нейросети: от 0 до 100.'))
        _color(self.background)
        self.adjust.validate()
        if self.size_mode in ('print', 'pixels'):
            w, h = self.target_pixels()
            if w * h > MAX_PIXELS:
                raise ValueError(tr('Результат больше 100 мегапикселей. Уменьшите размер или PPI.'))
        return self

    def target_pixels(self):
        if self.size_mode == 'pixels':
            return self.pixel_width, self.pixel_height
        if self.size_mode == 'print':
            return mm_to_px(self.width_mm, self.dpi), mm_to_px(self.height_mm, self.dpi)
        raise ValueError(tr('Размер зависит от снимка.'))

    def border_px(self):
        return mm_to_px(self.border_mm, self.dpi) if self.size_mode == 'print' and self.border_mm else 0

    def effective_sharpen(self):
        return self.sharpen

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Accepts 2.x dicts and flat 1.x settings; unknown keys are ignored."""
        if not isinstance(data, dict):
            raise ValueError(tr('Настройки должны быть объектом JSON.'))
        if 'adjust' not in data and any(k in data for k in ('enhancement_preset', 'auto_enhance', 'upscaler', 'chroma_denoise')):
            return migrate_v1(data)
        names = {f.name for f in fields(cls)} - {'adjust'}
        values = {k: v for k, v in data.items() if k in names}
        if 'upscaler' in data and 'neural' not in data:   # 2.0.0 had a choice of two networks
            values['neural'] = data['upscaler'] != 'off'
        adjust = data.get('adjust') or {}
        if not isinstance(adjust, dict):
            raise ValueError(tr('Некорректный блок коррекции.'))
        anames = {f.name for f in fields(Adjust)}
        settings = cls(**values, adjust=Adjust(**{k: v for k, v in adjust.items() if k in anames}))
        for key in ('dpi', 'pixel_width', 'pixel_height', 'long_edge', 'quality', 'bit_depth', 'intent'):
            value = getattr(settings, key)
            if isinstance(value, float) and value.is_integer():
                setattr(settings, key, int(value))
        return settings


@dataclass
class Edit:
    """Per-photo geometry and color offsets layered over the batch preset."""
    rotation: int = 0
    angle: float = 0.0
    fit: str | None = None
    aspect: float | None = None
    center_x: float = .5
    center_y: float = .5
    zoom: float = 1.0
    manual_crop: bool = False
    offsets: dict = field(default_factory=dict)
    neural: bool | None = None

    def validate(self):
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError(tr('Поворот кратен 90°.'))
        if not _finite(self.angle) or not -20 <= self.angle <= 20:
            raise ValueError(tr('Выравнивание горизонта: от −20° до 20°.'))
        if self.fit not in (None, 'cover', 'contain'):
            raise ValueError(tr('Некорректный режим кадра снимка.'))
        if self.aspect is not None and (not _finite(self.aspect) or not .1 <= self.aspect <= 10):
            raise ValueError(tr('Некорректные пропорции кадра.'))
        if not all(_finite(v) for v in (self.center_x, self.center_y, self.zoom)):
            raise ValueError(tr('Некорректный кадр.'))
        if not (0 <= self.center_x <= 1 and 0 <= self.center_y <= 1 and 1 <= self.zoom <= 8):
            raise ValueError(tr('Кадр за допустимыми пределами.'))
        if self.neural is not None and type(self.neural) is not bool:
            raise ValueError(tr('Некорректный переключатель нейросети.'))
        if not isinstance(self.offsets, dict):
            raise ValueError(tr('Некорректные правки цвета.'))
        for key, value in self.offsets.items():
            if key not in ADJUST_RANGES or not _finite(value):
                raise ValueError(tr('Некорректная правка «{key}».', key=key))
            _, low, high, _, _ = ADJUST_RANGES[key]
            if abs(value) > high - low:
                raise ValueError(tr('Правка «{v}» слишком велика.', v=tr(ADJUST_RANGES[key][0])))
        return self

    def is_default(self):
        return self == Edit() or (self.geometry_default() and not any(self.offsets.values()) and self.neural is None)

    def geometry_default(self):
        return (self.rotation == 0 and self.angle == 0 and self.fit is None and self.aspect is None
                and not self.manual_crop and self.zoom == 1)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError(tr('Правка снимка должна быть объектом JSON.'))
        if 'exposure' in data or 'use_neural' in data:
            return migrate_edit_v1(data)
        names = {f.name for f in fields(cls)}
        edit = cls(**{k: v for k, v in data.items() if k in names})
        edit.offsets = {k: float(v) for k, v in (edit.offsets or {}).items() if k in ADJUST_RANGES and v}
        return edit


def combined_adjust(settings: Settings, edit: Edit | None) -> Adjust:
    """Preset values plus per-photo offsets, clamped to slider ranges."""
    adjust = replace(settings.adjust)
    if edit and edit.offsets:
        for key, delta in edit.offsets.items():
            if key in ADJUST_RANGES:
                _, low, high, _, _ = ADJUST_RANGES[key]
                setattr(adjust, key, min(high, max(low, getattr(adjust, key) + delta)))
    return adjust


def mm_to_px(mm, dpi):
    return max(1, round(mm / 25.4 * dpi))


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _color(text):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(text)
    except Exception:
        raise ValueError(tr('Некорректный цвет полей.')) from None


def migrate_v1(data) -> Settings:
    """Best-effort translation of Print Prep 1.x settings (0..1 strengths, flags)."""
    keep = ('size_mode', 'width_mm', 'height_mm', 'dpi', 'pixel_width', 'pixel_height', 'long_edge', 'fit',
            'auto_orientation', 'border_mm', 'background', 'format', 'output_space', 'icc_path', 'intent',
            'smart_crop', 'allow_upscale')
    s = Settings(**{k: data[k] for k in keep if k in data})
    s.quality = int(min(100, max(50, data.get('quality', 95))))
    if s.size_mode == 'print' and data.get('sharpen'):
        s.sharpen = 'glossy'
    elif data.get('sharpen'):
        s.sharpen = 'screen'
    s.neural = data.get('upscaler') == 'fsrcnn'
    s.neural_strength = round(100 * float(data.get('neural_strength', .8)))
    k = float(data.get('enhancement_strength', .7)) * 100
    a = s.adjust
    a.shadows = round(float(data.get('shadows', 0)) * k)
    a.highlights = -round(float(data.get('highlights', 0)) * k)
    a.clarity = round(float(data.get('clarity', 0)) * k)
    a.vibrance = round(float(data.get('vibrance', 0)) * k)
    a.temperature = round(float(data.get('warmth', 0)) * k)
    a.tint = round(float(data.get('tint', 0)) * k)
    a.color_denoise = round(float(data.get('chroma_denoise', 0)) * k)
    if data.get('auto_wb') or data.get('auto_tone') or data.get('auto_enhance'):
        a.auto = True
        a.auto_strength = 50
        a.auto_wb = bool(data.get('auto_wb'))
    for key in NUMERIC_ADJUST:
        _, low, high, _, _ = ADJUST_RANGES[key]
        setattr(a, key, min(high, max(low, getattr(a, key))))
    return s


def migrate_edit_v1(data) -> Edit:
    edit = Edit(rotation=int(data.get('rotation', 0)) % 360, fit=data.get('fit'),
                center_x=float(data.get('center_x', .5)), center_y=float(data.get('center_y', .5)),
                zoom=float(data.get('zoom', 1)), manual_crop=bool(data.get('manual_crop', False)),
                neural=data.get('use_neural'))
    offsets = {'exposure': float(data.get('exposure', 0)),
               'contrast': round((float(data.get('contrast', 1)) - 1) * 100),
               'saturation': round((float(data.get('saturation', 1)) - 1) * 100)}
    edit.offsets = {k: v for k, v in offsets.items() if v}
    return edit


# ---------------------------------------------------------------- built-in presets
# Sizes: Russian/European "10×15" lab paper is 4×6″ = 102×152 mm, and so on.
PAPER_SIZES = [
    ('10 × 15 см · 102 × 152 мм', 102, 152),
    ('13 × 18 см · 127 × 178 мм', 127, 178),
    ('15 × 21 см · 152 × 216 мм', 152, 216),
    ('15 × 20 см · 152 × 203 мм', 152, 203),
    ('20 × 30 см · 203 × 305 мм', 203, 305),
    ('30 × 40 см · 305 × 406 мм', 305, 406),
    ('30 × 45 см · 305 × 457 мм', 305, 457),
    ('Квадрат 15 × 15 · 152 × 152 мм', 152, 152),
    ('A5 · 148 × 210 мм', 148, 210),
    ('A4 · 210 × 297 мм', 210, 297),
    ('A3 · 297 × 420 мм', 297, 420),
    ('A3+ · 329 × 483 мм', 329, 483),
]


def _auto(strength=60, **kw):
    return Adjust(auto=True, auto_strength=strength, **kw)


BUILTIN_PRESETS = {
    'original': dict(name='Без изменений', group='Основные',
                     note='Исходный размер и цвет · JPEG 95',
                     settings=Settings()),
    'smart': dict(name='Умное улучшение', group='Основные',
                  note='Исходный размер · авто свет, цвет, шум · лёгкая резкость',
                  settings=Settings(sharpen='screen', sharpen_amount='low', adjust=_auto(90))),
    'archive_tiff': dict(name='Архив TIFF 16 бит', group='Основные',
                         note='Исходный размер · TIFF 16 бит без потерь · без коррекции',
                         settings=Settings(format='TIFF', bit_depth=16)),
    'lab_10x15': dict(name='Фотолаборатория 10×15', group='Печать',
                      note='102×152 мм · 300 PPI · заполнение · авто · глянец',
                      settings=Settings(size_mode='print', sharpen='glossy', adjust=_auto(80))),
    'lab_15x21': dict(name='Фотолаборатория 15×21', group='Печать',
                      note='152×216 мм · 300 PPI · заполнение · авто · глянец',
                      settings=Settings(size_mode='print', width_mm=152, height_mm=216, sharpen='glossy', adjust=_auto(80))),
    'lab_20x30': dict(name='Фотолаборатория 20×30', group='Печать',
                      note='203×305 мм · 300 PPI · заполнение · авто · глянец',
                      settings=Settings(size_mode='print', width_mm=203, height_mm=305, sharpen='glossy', adjust=_auto(80))),
    'home_a4_matte': dict(name='Домашний принтер A4 · мат', group='Печать',
                          note='210×297 мм · весь кадр · резкость для матовой · +8% яркости',
                          settings=Settings(size_mode='print', width_mm=210, height_mm=297, fit='contain',
                                            sharpen='matte', print_brightness=8, adjust=_auto(70))),
    'screen_4k': dict(name='Экран 4K', group='Экран и веб',
                      note='3840 px по длинной стороне · резкость для экрана',
                      settings=Settings(size_mode='long_edge', long_edge=3840, sharpen='screen', adjust=_auto(70))),
    'web': dict(name='Соцсети и веб', group='Экран и веб',
                note='2048 px · JPEG 90 · резкость для экрана',
                settings=Settings(size_mode='long_edge', long_edge=2048, quality=90, sharpen='screen', adjust=_auto(80))),
    'upscale_small': dict(name='Увеличить маленькие фото', group='Нейросеть',
                          note='Нейросеть · 20×30 при 300 PPI · заполнение',
                          settings=Settings(size_mode='print', width_mm=203, height_mm=305, sharpen='glossy',
                                            neural=True, adjust=_auto(70))),
}
