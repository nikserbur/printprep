# Сторонние компоненты

Print Prep использует Pillow (MIT-CMU), LittleCMS (MIT), NumPy (BSD и уведомления о включённых компонентах), OpenCV (Apache-2.0 и уведомления о включённых компонентах), FSRCNN ×2 (Apache-2.0), PySide6/Qt и Shiboken (доступны по LGPLv3/GPLv3 или коммерческой лицензии), PyInstaller (GPL с исключением для распространяемых приложений). В библиотеках могут быть дополнительные кодеки со своими лицензиями. Сборщик копирует найденные тексты лицензий из фактически установленного окружения, а также сохранённые тексты licenses/ в `licenses/` рядом с exe; сохраняйте их в поставке.

Исходный код Print Prep и сценарий сборки доступны в этом репозитории. Для замены динамических Qt-библиотек и пересборки используйте Windows + Python 3.12 x64, requirements-dev.txt и build_exe.bat. Onefile распаковывает динамические библиотеки во временный каталог; для удобства замены можно собрать `--onedir` вместо `--onefile`. Не запрещайте получателям отладку для изменения LGPL-компонентов. Для выбранной схемы коммерческого распространения проверьте обязанности LGPL и полные уведомления Qt; наличие этого файла не заменяет соблюдения лицензий.

Ссылки на исходные проекты и условия:
- https://github.com/python-pillow/Pillow
- https://github.com/mm2/Little-CMS
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://github.com/pyinstaller/pyinstaller

ICC-профили производителей и тестовый Ghostscript CMYK-профиль не входят в исходный проект или релиз. Пользователь выбирает свой профиль и соблюдает условия его использования. Print Prep не аффилирован с производителями принтеров и фотолабораториями.

Встроенная FSRCNN ×2: https://github.com/Saafke/FSRCNN_Tensorflow — авторская TensorFlow-реализация для OpenCV GSoC, T91/General100, исходная статья Dong/Loy/Tang (ECCV 2016). Сведения о файле и SHA-256 — assets/models/README.md; лицензия — licenses/FSRCNN-Apache-2.0.txt. Инференс выполняет OpenCV DNN без TensorFlow/PyTorch.
