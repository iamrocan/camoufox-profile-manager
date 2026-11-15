#!/usr/bin/env python3
"""Create the Desktop shortcut, and say exactly what happened.

`install.py --shortcut-only` does this too, and reports a failure in one line.
This exists for when that line is not enough: it prints every step, the full
traceback of whatever broke, and falls back to a .bat on the Desktop so the
machine ends up with *something* that opens the app.

Stdlib only, and runnable on its own -- fetch it and run it without a checkout:

    curl.exe -L -o "%TEMP%\\mk.py" https://raw.githubusercontent.com/iamrocan/camoufox-profile-manager/main/scripts/make_shortcut.py
    python "%TEMP%\\mk.py" "C:\\Camoufox Persistente"

With no argument it uses the folder two levels up from this file, which is the
install when it is run from a checkout.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from ctypes import c_void_p, c_wchar_p, wintypes
from pathlib import Path

NAME = "Camoufox Profile Manager"

CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def say(label: str, value: object = "") -> None:
    print(f"  {label:<26}{value}", flush=True)


def guid(text: str):
    buf = (ctypes.c_byte * 16)()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.create_unicode_buffer(text), ctypes.byref(buf))
    return buf


def method(ptr, slot, restype, *argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[slot])


def desktop_dir() -> Path:
    try:
        out = c_wchar_p()
        ctypes.oledll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid(FOLDERID_DESKTOP)), 0, wintypes.HANDLE(0), ctypes.byref(out)
        )
        try:
            return Path(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        say("SHGetKnownFolderPath", "fallo; usando rutas conocidas")
        home = Path.home() / "Desktop"
        if home.is_dir():
            return home
        one = Path(os.environ.get("OneDrive", "")) / "Desktop"
        return one if one.is_dir() else home


def write_lnk(link: Path, target: Path, arguments: str, workdir: Path, icon: Path | None) -> None:
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    try:
        shell = c_void_p()
        ole32.CoCreateInstance(
            ctypes.byref(guid(CLSID_SHELL_LINK)),
            None,
            1,
            ctypes.byref(guid(IID_SHELL_LINK_W)),
            ctypes.byref(shell),
        )
        try:
            method(shell, 20, ctypes.HRESULT, c_wchar_p)(shell, c_wchar_p(str(target)))
            method(shell, 11, ctypes.HRESULT, c_wchar_p)(shell, c_wchar_p(arguments))
            method(shell, 9, ctypes.HRESULT, c_wchar_p)(shell, c_wchar_p(str(workdir)))
            method(shell, 7, ctypes.HRESULT, c_wchar_p)(shell, c_wchar_p(NAME))
            if icon is not None:
                method(shell, 17, ctypes.HRESULT, c_wchar_p, ctypes.c_int)(
                    shell, c_wchar_p(str(icon)), 0
                )
            persist = c_void_p()
            method(shell, 0, ctypes.HRESULT, c_void_p, c_void_p)(
                shell, ctypes.byref(guid(IID_PERSIST_FILE)), ctypes.byref(persist)
            )
            try:
                method(persist, 6, ctypes.HRESULT, c_wchar_p, ctypes.c_int)(
                    persist, c_wchar_p(str(link)), 1
                )
            finally:
                method(persist, 2, ctypes.c_ulong)(persist)
        finally:
            method(shell, 2, ctypes.c_ulong)(shell)
    finally:
        ctypes.windll.ole32.CoUninitialize()


def write_bat(path: Path, pythonw: Path, script: Path, workdir: Path) -> None:
    """Last resort. A console flashes for an instant; the app opens all the same."""
    path.write_text(
        "@echo off\r\n"
        f'cd /d "{workdir}"\r\n'
        f'start "" "{pythonw}" "{script}" --desktop\r\n',
        encoding="utf-8",
    )


def main() -> int:
    if os.name != "nt":
        print("Esto solo sirve en Windows.")
        return 1

    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent

    # A plain hyphen on purpose: this runs on a machine that is already having
    # trouble, often in a console on a legacy code page, where an em dash
    # arrives as a replacement glyph and makes the first line look broken.
    print(f"\n{NAME} - creando el acceso directo\n")
    say("Python", sys.version.split()[0])
    say("ejecutable", sys.executable)
    say("carpeta de instalacion", target)

    pythonw = target / ".venv" / "Scripts" / "pythonw.exe"
    script = target / "scripts" / "prelaunch.py"
    icon = target / "camoufox.ico"

    say(".venv/pythonw.exe", "OK" if pythonw.is_file() else "NO EXISTE")
    say("scripts/prelaunch.py", "OK" if script.is_file() else "NO EXISTE")
    say("camoufox.ico", "OK" if icon.is_file() else "no (se omite el icono)")

    if not pythonw.is_file():
        print("\nFALLO: esa carpeta no tiene un entorno instalado.")
        print("Pasa la carpeta correcta, por ejemplo:")
        print('  python make_shortcut.py "C:\\Camoufox Persistente"')
        return 1

    if script.is_file():
        arguments = f'"{script}" --desktop'
    else:
        # An older checkout has no prelaunch; the app still opens.
        arguments = "-m camoufox_pm.cli --desktop"
        say("aviso", "sin prelaunch.py: no buscara actualizaciones")

    desktop = desktop_dir()
    say("Escritorio", desktop)
    link = desktop / f"{NAME}.lnk"

    print()
    try:
        write_lnk(link, pythonw, arguments, target, icon if icon.is_file() else None)
    except Exception:
        print("El metodo normal fallo. Traceback completo:\n")
        traceback.print_exc()
        bat = desktop / f"{NAME}.bat"
        print(f"\nPlan B: escribiendo {bat}")
        try:
            write_bat(bat, pythonw, script, target)
        except Exception:
            traceback.print_exc()
            return 1
        print("Listo. Doble clic en ese .bat abre la aplicacion.")
        print("(parpadea una consola un instante; es normal)")
        return 0

    if not link.is_file():
        print(f"FALLO: no quedo escrito {link}")
        return 1

    print(f"Creado: {link}")
    print("\nListo. Doble clic en el acceso directo del escritorio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
