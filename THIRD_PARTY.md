# Сторонние компоненты

Print Prep использует Pillow (MIT-CMU), LittleCMS (MIT), NumPy (BSD и уведомления о включённых компонентах), OpenCV opencv-python-headless (Apache-2.0 и уведомления о включённых компонентах), Real-ESRGAN general x4v3 (BSD-3-Clause), YuNet (MIT), PySide6/Qt и Shiboken (доступны по LGPLv3/GPLv3 или коммерческой лицензии), PyInstaller (GPL с исключением для распространяемых приложений). В библиотеках могут быть дополнительные кодеки со своими лицензиями. Сборщик копирует найденные тексты лицензий из фактически установленного окружения, а также сохранённые тексты licenses/ в `licenses/` рядом с exe; сохраняйте их в поставке.

Исходный код Print Prep и сценарий сборки доступны в этом репозитории. Для замены динамических Qt-библиотек и пересборки используйте Windows + Python 3.12 x64, requirements-dev.txt и build_exe.bat. Onefile распаковывает динамические библиотеки во временный каталог; для удобства замены можно собрать `--onedir` вместо `--onefile`. Не запрещайте получателям отладку для изменения LGPL-компонентов. Для выбранной схемы коммерческого распространения проверьте обязанности LGPL и полные уведомления Qt; наличие этого файла не заменяет соблюдения лицензий.

Ссылки на исходные проекты и условия:
- https://github.com/python-pillow/Pillow
- https://github.com/mm2/Little-CMS
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/
- https://github.com/pyinstaller/pyinstaller

ICC-профили производителей и тестовый Ghostscript CMYK-профиль не входят в исходный проект или релиз. Пользователь выбирает свой профиль и соблюдает условия его использования. Print Prep не аффилирован с производителями принтеров и фотолабораториями.



Встроенная Real-ESRGAN general x4v3: официальные веса https://github.com/xinntao/Real-ESRGAN (BSD-3-Clause), ONNX-экспорт с https://huggingface.co/jonathanst29/tinier-upscale-models; лицензия — licenses/Real-ESRGAN-BSD-3-Clause.txt.
Веса Real-ESRGAN general wdn x4v3 (для регулировки «Чистота ↔ Детали»): официальный релиз v0.2.5.0, https://github.com/xinntao/Real-ESRGAN/releases (BSD-3-Clause), преобразованы в NumPy скриптом tools/convert_wdn.py.
Встроенный детектор лиц YuNet 2023mar: https://huggingface.co/opencv/face_detection_yunet (OpenCV Zoo, MIT); лицензия — licenses/YuNet-MIT.txt. Размеры файлов и SHA-256 — assets/models/README.md.
Иконки интерфейса и логотип (абстрактная композиция по мотивам «Нескольких кругов» Кандинского, без копирования картины) нарисованы для Print Prep кодом в tools/make_icon.py и не заимствованы из сторонних наборов.
