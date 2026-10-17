"""Interface language. Russian strings are the keys; English lives in i18n_en.

tr() is called when a widget is built, so switching the language only needs the window
to be rebuilt. Unknown strings fall back to the original text (user preset names, file
names, error text from the OS).
"""
from __future__ import annotations

LANGUAGES = (('ru', 'Русский'), ('en', 'English'))
LANG = 'ru'


def default_language():
    try:
        from PySide6.QtCore import QLocale
        return 'ru' if QLocale.system().language() in (QLocale.Language.Russian, QLocale.Language.Ukrainian,
                                                        QLocale.Language.Belarusian, QLocale.Language.Kazakh) else 'en'
    except Exception:
        return 'ru'


def set_language(code):
    global LANG
    LANG = code if code in dict(LANGUAGES) else 'ru'
    return LANG


def tr(text, **values):
    """Translate `text` (the Russian original) and fill its {fields}.

    English templates may use {s} for a plural ending; it follows `n`, or the first integer
    value: tr('Подготовить {n} фото', n=1) → 'Prepare 1 photo', n=3 → 'Prepare 3 photos'.
    """
    if LANG == 'en' and text:
        from .i18n_en import EN
        text = EN.get(text, text)
        if '{s}' in text and 's' not in values:
            count = values.get('n', next((v for v in values.values() if isinstance(v, int)), 2))
            values = dict(values, s='' if count == 1 else 's')
    return text.format(**values) if values else text

