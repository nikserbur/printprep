"""Print Prep one-click installer (Windows, per user, no admin rights).

Built into a single PrintPrep-Setup.exe by installer/setup.spec; the app itself travels inside as
PrintPrep-Windows-x64.zip. It installs to %LOCALAPPDATA%\\Programs\\Print Prep, adds Start menu and
desktop shortcuts, registers in "Apps & features" (uninstall runs PrintPrep.exe --uninstall) and
starts the app.

Command line (for IT and the build check):
  --silent          install with defaults, no window
  --target DIR      install folder
  --no-shortcuts    skip Start menu and desktop shortcuts
  --no-register     skip the "Apps & features" entry
  --no-launch       do not start the app afterwards
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

APP = 'Print Prep'
EXE = 'PrintPrep.exe'
REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintPrep'
MARKER = '.printprep-install'
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

try:
    from printprep import __version__ as VERSION
except Exception:
    VERSION = ''


def bundled(name):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    for candidate in (base / name, Path(__file__).resolve().parents[1] / 'dist' / name,
                      Path(__file__).resolve().parents[1] / 'assets' / name):
        if candidate.exists():
            return candidate
    return base / name


def russian():
    try:
        return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF in (0x19, 0x22, 0x23, 0x3F)
    except Exception:
        return True


RU = russian()
TEXT = {
    'title': ('Установка Print Prep', 'Print Prep Setup'),
    'tagline': ('Подготовка фотографий к печати', 'Preparing photos for print'),
    'where': ('Папка установки:', 'Install folder:'),
    'change': ('Изменить…', 'Change…'),
    'desktop': ('Ярлык на рабочем столе', 'Desktop shortcut'),
    'launch': ('Запустить после установки', 'Start after installing'),
    'install': ('Установить', 'Install'),
    'update': ('Обновить', 'Update'),
    'reinstall': ('Переустановить', 'Reinstall'),
    'installing': ('Устанавливаем…', 'Installing…'),
    'copying': ('Копируем файлы… {p}%', 'Copying files… {p}%'),
    'shortcuts': ('Создаём ярлыки…', 'Creating shortcuts…'),
    'done': ('Готово! Print Prep установлен.', 'Done! Print Prep is installed.'),
    'start': ('Запустить Print Prep', 'Start Print Prep'),
    'close': ('Закрыть', 'Close'),
    'running': ('Print Prep сейчас открыт. Закройте его и нажмите «{b}» ещё раз.',
                'Print Prep is open. Close it and press “{b}” again.'),
    'failed': ('Не удалось установить:\n{e}', 'Installation failed:\n{e}'),
    'note': ('Права администратора не нужны. Ваши пресеты и настройки сохранятся при обновлении.',
             'No admin rights needed. Your presets and settings are kept on update.'),
    'found': ('Уже установлена версия {v}.', 'Version {v} is already installed.'),
}


def t(key, **values):
    text = TEXT[key][0 if RU else 1]
    return text.format(**values) if values else text


def default_target():
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(base) / 'Programs' / APP


def installed_version(target):
    try:
        return json.loads((Path(target) / MARKER).read_text(encoding='utf-8')).get('version', '')
    except Exception:
        return None


def resolve_target(chosen):
    """A chosen non-empty folder gets its own "Print Prep" subfolder; never install into, or clean, a foreign folder."""
    chosen = Path(chosen)
    if (chosen / MARKER).exists() or chosen.name == APP or not chosen.exists() or not any(chosen.iterdir()):
        return chosen
    return chosen / APP


def app_running(target):
    exe = Path(target) / EXE
    if not exe.exists():
        return False
    try:
        probe = exe.with_suffix('.exe.probe')
        exe.rename(probe)          # Windows refuses to rename a running executable
        probe.rename(exe)
        return False
    except OSError:
        return True


def special_folder(name):
    """Desktop / Start menu Programs, honouring OneDrive or roaming redirection."""
    script = f"[Environment]::GetFolderPath('{name}')"
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True,
                             text=True, timeout=30, creationflags=CREATE_NO_WINDOW).stdout.strip()
        if out:
            return Path(out)
    except Exception:
        pass
    fallback = {'Desktop': Path.home() / 'Desktop',
                'Programs': Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'}
    return fallback[name]


def make_shortcut(link, exe):
    env = dict(os.environ, PP_LINK=str(link), PP_EXE=str(exe), PP_DIR=str(Path(exe).parent))
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PP_LINK); $s.TargetPath = $env:PP_EXE; "
              "$s.WorkingDirectory = $env:PP_DIR; $s.IconLocation = $env:PP_EXE + ',0'; "
              "$s.Description = 'Print Prep'; $s.Save()")
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                   env=env, timeout=60, creationflags=CREATE_NO_WINDOW, check=True)


def register(target, size_kb):
    import winreg
    exe = str(Path(target) / EXE)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
        for name, value in (('DisplayName', APP), ('DisplayVersion', VERSION), ('Publisher', APP),
                            ('DisplayIcon', exe + ',0'), ('InstallLocation', str(target)),
                            ('UninstallString', f'"{exe}" --uninstall'), ('QuietUninstallString', f'"{exe}" --uninstall --quiet')):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in (('NoModify', 1), ('NoRepair', 1), ('EstimatedSize', int(size_kb))):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def refresh_shell(exe):
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHChangeNotify(0x2000, 0x0005, ctypes.c_wchar_p(str(exe)), None)      # SHCNE_UPDATEITEM
        shell32.SHChangeNotify(0x08000000, 0, None, None)                              # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def install(target, desktop=True, shortcuts=True, registry=True, progress=None):
    """Unpack the bundled app into `target` (a clean replacement of an earlier install)."""
    target = Path(target)
    payload = bundled('PrintPrep-Windows-x64.zip')
    if not payload.exists():
        raise FileNotFoundError(payload)
    if (target / MARKER).exists():
        shutil.rmtree(target / '_internal', ignore_errors=True)   # no stale libraries from an older version
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        total = sum(m.file_size for m in members) or 1
        done = 0
        for m in members:
            name = m.filename.split('/', 1)[1] if m.filename.startswith('PrintPrep/') else m.filename
            dest = (target / name).resolve()
            if target.resolve() not in dest.parents:
                raise ValueError(f'unsafe path in archive: {m.filename}')
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(m) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out, 1 << 20)
            done += m.file_size
            if progress:
                progress('copy', done / total)
    links = []
    exe = target / EXE
    if shortcuts:
        if progress:
            progress('shortcuts', 1.)
        links.append(special_folder('Programs') / f'{APP}.lnk')
        if desktop:
            links.append(special_folder('Desktop') / f'{APP}.lnk')
        for link in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            make_shortcut(link, exe)
    (target / MARKER).write_text(json.dumps({'version': VERSION, 'shortcuts': [str(x) for x in links],
                                             'registered': registry}, ensure_ascii=False), encoding='utf-8')
    if registry:
        register(target, total / 1024)
    refresh_shell(exe)
    return exe


def launch(exe):
    subprocess.Popen([str(exe)], cwd=str(Path(exe).parent), close_fds=True,
                     creationflags=DETACHED_PROCESS | 0x00000200)          # CREATE_NEW_PROCESS_GROUP


# ---------------------------------------------------------------- window
def run_window():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title(f'{t("title")} {VERSION}')
    root.resizable(False, False)
    try:
        root.iconbitmap(str(bundled('printprep.ico')))
    except Exception:
        pass
    style = ttk.Style(root)
    if 'vista' in style.theme_names():
        style.theme_use('vista')
    bg = '#ffffff'
    root.configure(bg=bg)
    style.configure('TFrame', background=bg)
    style.configure('TLabel', background=bg)
    style.configure('TCheckbutton', background=bg)
    style.configure('Title.TLabel', font=('Segoe UI Semibold', 18), background=bg)
    style.configure('Muted.TLabel', foreground='#5f6470', background=bg)
    style.configure('Path.TLabel', foreground='#1d4fb0', background=bg)

    frame = ttk.Frame(root, padding=(26, 22, 26, 20))
    frame.grid(sticky='nsew')
    head = ttk.Frame(frame)
    head.grid(row=0, column=0, columnspan=2, sticky='w')
    try:
        logo = tk.PhotoImage(file=str(bundled('printprep.png')))
        factor = max(1, round(logo.width() / 84))
        logo = logo.subsample(factor, factor)
        tk.Label(head, image=logo, bg=bg).grid(row=0, column=0, rowspan=2, padx=(0, 16))
        root._logo = logo
    except Exception:
        pass
    ttk.Label(head, text=APP, style='Title.TLabel').grid(row=0, column=1, sticky='sw')
    ttk.Label(head, text=f'{t("tagline")} · {VERSION}', style='Muted.TLabel').grid(row=1, column=1, sticky='nw')

    state = {'target': default_target()}
    ttk.Label(frame, text=t('where')).grid(row=1, column=0, columnspan=2, sticky='w', pady=(22, 2))
    path_label = ttk.Label(frame, text=str(state['target']), style='Path.TLabel', wraplength=420)
    path_label.grid(row=2, column=0, sticky='w')
    found = ttk.Label(frame, text='', style='Muted.TLabel')
    found.grid(row=3, column=0, columnspan=2, sticky='w', pady=(2, 0))

    desktop = tk.BooleanVar(value=True)
    start = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text=t('desktop'), variable=desktop).grid(row=4, column=0, columnspan=2, sticky='w', pady=(14, 0))
    ttk.Checkbutton(frame, text=t('launch'), variable=start).grid(row=5, column=0, columnspan=2, sticky='w', pady=(4, 0))
    ttk.Label(frame, text=t('note'), style='Muted.TLabel', wraplength=440).grid(row=6, column=0, columnspan=2, sticky='w', pady=(14, 0))

    bar = ttk.Progressbar(frame, length=440, mode='determinate', maximum=1000)
    status = ttk.Label(frame, text='', style='Muted.TLabel')
    accent, accent_hover, accent_off = '#2f6fe4', '#2462d3', '#9db8ec'
    button = tk.Button(frame, font=('Segoe UI Semibold', 11), bg=accent, fg='#ffffff', activebackground=accent_hover,
                       activeforeground='#ffffff', disabledforeground='#eef3fd', relief='flat', bd=0, padx=26, pady=8,
                       cursor='hand2', highlightthickness=0)
    button.grid(row=9, column=0, columnspan=2, sticky='e', pady=(18, 0))
    button.bind('<Enter>', lambda _: button['state'] != 'disabled' and button.configure(bg=accent_hover))
    button.bind('<Leave>', lambda _: button.configure(bg=accent if button['state'] != 'disabled' else accent_off))

    def refresh_target():
        path_label.configure(text=str(state['target']))
        version = installed_version(state['target'])
        found.configure(text=t('found', v=version) if version else '')
        button.configure(text=t('reinstall') if version == VERSION else t('update') if version is not None else t('install'))

    def change():
        chosen = filedialog.askdirectory(initialdir=str(state['target'].parent), title=t('where'))
        if chosen:
            state['target'] = resolve_target(chosen)
            refresh_target()
    change_btn = ttk.Button(frame, text=t('change'), command=change)
    change_btn.grid(row=2, column=1, sticky='e', padx=(12, 0))
    refresh_target()

    def finish(exe):
        bar.configure(value=1000)
        status.configure(text=t('done'))
        if start.get():
            launch(exe)
            root.after(600, root.destroy)
            return
        button.configure(text=t('start'), state='normal', bg=accent, command=lambda: (launch(exe), root.destroy()))
        ttk.Button(frame, text=t('close'), command=root.destroy).grid(row=9, column=0, sticky='w', pady=(18, 0))

    def fail(error):
        status.configure(text='')
        button.configure(state='normal', bg=accent)
        change_btn.configure(state='normal')
        messagebox.showerror(t('title'), t('failed', e=error))

    def go():
        target = state['target']
        if app_running(target):
            messagebox.showwarning(t('title'), t('running', b=button.cget('text')))
            return
        button.configure(state='disabled', bg=accent_off)
        change_btn.configure(state='disabled')
        bar.grid(row=7, column=0, columnspan=2, sticky='we', pady=(16, 0))
        status.grid(row=8, column=0, columnspan=2, sticky='w', pady=(4, 0))
        status.configure(text=t('installing'))

        def report(stage, fraction):
            text = t('copying', p=round(fraction * 100)) if stage == 'copy' else t('shortcuts')
            root.after(0, lambda: (bar.configure(value=fraction * 950), status.configure(text=text)))

        def work():
            try:
                exe = install(target, desktop=desktop.get(), progress=report)
                root.after(0, lambda: finish(exe))
            except Exception as e:
                root.after(0, lambda e=e: fail(e))
        threading.Thread(target=work, daemon=True).start()

    button.configure(command=go)
    root.bind('<Return>', lambda _: button['state'] != 'disabled' and button.invoke())
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f'+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}')
    button.focus_set()
    root.mainloop()


def main(argv):
    if '--silent' not in argv:
        run_window()
        return 0
    try:
        target = Path(argv[argv.index('--target') + 1]) if '--target' in argv else default_target()
        if app_running(target):
            return 2
        exe = install(target, shortcuts='--no-shortcuts' not in argv, registry='--no-register' not in argv)
        if '--no-launch' not in argv:
            launch(exe)
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
