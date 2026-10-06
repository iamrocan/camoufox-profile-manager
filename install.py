#!/usr/bin/env python3
"""Install Camoufox Profile Manager on a Windows machine that only has Python.

Reproduces a working desktop install: the code, the exact dependency versions
from uv.lock, the browser itself, and a Desktop shortcut that opens the app in
its own window with no console behind it.

Deliberately stdlib only. The whole premise is a machine with nothing but
Python on it, so an installer that needs its own dependencies installed first
would not solve the problem it exists for.

What it does NOT do is carry over profiles. The database holds proxy passwords,
and on an install with CPM_SECRET_KEY unset it holds them as plain text, so
moving it is a decision rather than a side effect of running a script. The
closing notes say how to do it on purpose.

Usage, from a folder containing this file:

    python install.py                      # Desktop\\Camoufox Persistente
    python install.py --dir D:\\Camoufox     # somewhere else
    python install.py --no-browser         # skip the ~200 MB browser download
    python install.py --no-shortcut        # no Desktop shortcut

Re-running it is safe: an existing install is updated in place, not replaced.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_URL = "https://github.com/iamrocan/camoufox-profile-manager.git"
ZIP_URL = "https://github.com/iamrocan/camoufox-profile-manager/archive/refs/heads/main.zip"
SHORTCUT_NAME = "Camoufox Profile Manager"
MIN_PYTHON = (3, 10)

IS_WINDOWS = os.name == "nt"


# --- output ------------------------------------------------------------------
#
# Numbered steps, because the two slow ones (dependency resolution and the
# browser download) look identical to a hang if you cannot see where you are.

_step = 0


def step(message: str) -> None:
    global _step
    _step += 1
    print(f"\n[{_step}] {message}", flush=True)


def info(message: str) -> None:
    print(f"    {message}", flush=True)


def warn(message: str) -> None:
    print(f"    ! {message}", flush=True)


def die(message: str, *, hint: str = "") -> None:
    print(f"\nFALLÓ: {message}", file=sys.stderr)
    if hint:
        print(f"       {hint}", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], *, cwd: Path | None = None, what: str = "") -> None:
    """Run a command, showing its output, and stop the install if it fails.

    Output is inherited rather than captured: these commands take minutes and
    their progress is the only sign the install is still moving.
    """
    info(f"$ {subprocess.list2cmdline(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        die(
            f"{what or 'el comando'} terminó con código {result.returncode}",
            hint="Revisa el error de arriba. Si fue de red, reintenta: "
            "volver a ejecutar install.py continúa donde quedó.",
        )


# --- preconditions -----------------------------------------------------------


def check_python() -> None:
    step(f"Comprobando Python (se necesita {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o superior)")
    if sys.version_info < MIN_PYTHON:
        die(
            f"Python {sys.version.split()[0]} es demasiado antiguo",
            hint=f"Instala Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ desde python.org "
            "y vuelve a ejecutar este script con esa versión.",
        )
    info(f"Python {sys.version.split()[0]} — correcto")

    if not IS_WINDOWS:
        warn(
            "Este script está hecho para Windows. El código y las dependencias se "
            "instalarán igual, pero los lanzadores (.vbs/.bat) y el acceso directo "
            "son de Windows y se omitirán."
        )


# --- getting the code --------------------------------------------------------


def fetch_code(target: Path) -> bool:
    """Put the repository in `target`. Returns True when git is managing it.

    git is preferred purely so later updates are one `git pull`. The zip path
    exists because requiring git would contradict the point of this script, and
    it is a one-way install: say so rather than let it be discovered later.
    """
    git = shutil.which("git")

    if (target / ".git").is_dir():
        step(f"Actualizando la instalación existente en {target}")
        if not git:
            warn("git no está disponible; se deja el código tal como está.")
            return True
        run([git, "pull", "--ff-only"], cwd=target, what="git pull")
        return True

    if target.exists() and any(target.iterdir()):
        die(
            f"{target} ya existe y no está vacía, pero no es un clon de git",
            hint="Usa --dir para elegir otra carpeta, o mueve esa carpeta "
            "a un lado y vuelve a ejecutar el script.",
        )

    if git:
        step(f"Clonando el repositorio en {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        run([git, "clone", "--depth", "1", REPO_URL, str(target)], what="git clone")
        return True

    step(f"Descargando el repositorio en {target} (git no está instalado)")
    warn(
        "Sin git esta instalación no se puede actualizar con `git pull`. "
        "Para poder actualizarla, instala git y vuelve a ejecutar el script."
    )
    download_zip(target)
    return False


def download_zip(target: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "repo.zip"
        info(f"Descargando {ZIP_URL}")
        try:
            urllib.request.urlretrieve(ZIP_URL, archive)
        except OSError as error:
            die(f"no se pudo descargar el repositorio: {error}",
                hint="Comprueba la conexión a internet y que el repositorio sea accesible.")

        info("Extrayendo…")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)

        # GitHub wraps everything in one <repo>-<branch> folder.
        roots = [p for p in Path(tmp).iterdir() if p.is_dir() and p.name != "__MACOSX"]
        if len(roots) != 1:
            die("el archivo descargado no tiene la forma esperada")

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(roots[0]), str(target))


# --- uv ----------------------------------------------------------------------


def ensure_uv() -> list[str]:
    """Return the command that invokes uv, installing it with pip if needed.

    uv is what makes this install match the original rather than merely work:
    `uv sync` reads uv.lock and pins every version, down to the transitive ones.
    """
    step("Comprobando uv (el gestor de paquetes que fija las versiones)")

    on_path = shutil.which("uv")
    if on_path and _uv_works([on_path]):
        info(f"uv ya está instalado: {on_path}")
        return [on_path]

    info("uv no está; instalándolo con pip")
    pip_base = [sys.executable, "-m", "pip", "install", "--upgrade", "uv"]
    if subprocess.run(pip_base).returncode != 0:
        # A system-wide Python the user cannot write to is the usual reason.
        info("Reintentando con --user")
        run(pip_base + ["--user"], what="pip install --user uv")

    # Prefer `python -m uv`: it does not depend on Scripts/ being on PATH,
    # which a fresh Python install very often is not.
    module_form = [sys.executable, "-m", "uv"]
    if _uv_works(module_form):
        return module_form

    found = shutil.which("uv")
    if found and _uv_works([found]):
        return [found]

    die(
        "uv quedó instalado pero no se puede ejecutar",
        hint="Abre una terminal nueva y prueba `python -m uv --version`.",
    )
    raise AssertionError("unreachable")


def _uv_works(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd + ["--version"], capture_output=True, text=True)
    except OSError:
        return False
    if result.returncode != 0:
        return False
    info((result.stdout or "").strip() or "uv disponible")
    return True


def sync_dependencies(uv: list[str], target: Path) -> None:
    step("Instalando dependencias con las versiones exactas de uv.lock")
    info("Esto puede tardar varios minutos la primera vez.")
    # --extra desktop brings pywebview, which is what gives the app its own
    # window instead of opening a browser tab.
    run(uv + ["sync", "--extra", "desktop"], cwd=target, what="uv sync")


# --- the browser -------------------------------------------------------------


def fetch_browser(target: Path) -> None:
    step("Descargando el navegador Camoufox")
    info("Son unos 200 MB y se guardan en la caché del usuario, fuera de esta carpeta.")
    camoufox = venv_bin(target, "camoufox")
    if not camoufox.exists():
        die(
            f"no se encontró {camoufox}",
            hint="La instalación de dependencias no terminó bien. Vuelve a ejecutar el script.",
        )
    run([str(camoufox), "fetch"], cwd=target, what="camoufox fetch")


# --- verification ------------------------------------------------------------


def verify(target: Path) -> None:
    """Check the one thing that silently half-works: the compiled interface.

    Without the bundle under src/camoufox_pm/webui the app still starts and the
    API still answers, so a smoke test that only checks "does it run" passes
    while the window shows nothing but API docs. Ask the app itself where it
    would serve the interface from, which is the question that actually matters.
    """
    step("Verificando que la interfaz compilada esté presente y se sirva")

    bundle = target / "src" / "camoufox_pm" / "webui"
    if not (bundle / "index.html").is_file():
        die(
            f"falta la interfaz compilada en {bundle}",
            hint="El repositorio debería traerla ya compilada. Si clonaste otra rama, "
            "reconstrúyela con Node: cd web && npm install && cd .. && "
            "python scripts/build_webui.py",
        )

    python = venv_bin(target, "python")
    if not python.exists():
        die(
            f"no se encontró {python}",
            hint="El entorno virtual no se creó. Vuelve a ejecutar el script.",
        )

    probe = (
        "from camoufox_pm.main import _webui_dir;"
        "d = _webui_dir();"
        "print('WEBUI_OK' if d else 'WEBUI_MISSING')"
    )
    result = subprocess.run(
        [str(python), "-c", probe], cwd=str(target), capture_output=True, text=True
    )
    if "WEBUI_OK" not in (result.stdout or ""):
        die(
            "la aplicación arranca pero no encuentra la interfaz",
            hint=(result.stderr or result.stdout or "").strip()[:500],
        )
    info("La interfaz se sirve correctamente.")


# --- launchers and shortcut --------------------------------------------------


def venv_bin(target: Path, name: str) -> Path:
    sub = "Scripts" if IS_WINDOWS else "bin"
    suffix = ".exe" if IS_WINDOWS else ""
    return target / ".venv" / sub / f"{name}{suffix}"


def create_shortcut(target: Path) -> Path | None:
    step("Creando el acceso directo en el escritorio")

    launcher = target / "launch.vbs"
    icon = target / "camoufox.ico"
    if not launcher.is_file():
        warn(f"no se encontró {launcher}; se omite el acceso directo.")
        return None

    # Built by PowerShell because the shortcut format is a COM object, and the
    # script is written to a file so no quoting has to survive two shells.
    ps = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop '{SHORTCUT_NAME}.lnk'
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = '{launcher}'
$sc.WorkingDirectory = '{target}'
$sc.Description = 'Camoufox Profile Manager'
{f"$sc.IconLocation = '{icon}'" if icon.is_file() else ""}
$sc.Save()
Write-Output $link
"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "shortcut.ps1"
        script.write_text(ps, encoding="utf-8")
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
            ],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        warn(f"no se pudo crear el acceso directo: {(result.stderr or '').strip()[:300]}")
        warn(f"Puedes abrir la app igualmente con {launcher}")
        return None

    link = (result.stdout or "").strip().splitlines()
    path = Path(link[-1]) if link else None
    info(f"Acceso directo: {path}")
    return path


# --- summary -----------------------------------------------------------------


def report(target: Path, shortcut: Path | None, git_managed: bool) -> None:
    print("\n" + "=" * 70)
    print("  Instalación terminada")
    print("=" * 70)

    print(f"\nCarpeta de la instalación:  {target}")
    print(f"Base de datos de perfiles:  {target / 'data' / 'profiles.db'}")
    if shortcut:
        print(f"Acceso directo:             {shortcut}")

    print("\nCÓMO ABRIRLO")
    print(f"  Doble clic en el acceso directo, o en {target / 'launch.vbs'}")
    print(f"  Si algo falla, usa {target / 'launch.bat'}: abre consola y muestra el error.")

    print("\nQUÉ RESPALDAR")
    print(f"  Solo la carpeta {target / 'data'}. Ahí están los perfiles, sus")
    print("  fingerprints fijados y los datos de navegación. Todo lo demás se")
    print("  reinstala con este script.")

    print("\nPARA LLEVAR LOS PERFILES DE LA OTRA PC")
    print("  Este script NO los copia, a propósito. Dos opciones, ambas desde el")
    print("  menú de cada perfil o la barra superior:")
    print("    - Exportar a Excel  -> importar aquí (varios perfiles de una vez)")
    print("    - Exportar…         -> importar aquí (uno, con cookies y sesión)")
    print("  AVISO: ambos archivos llevan las contraseñas de proxy en texto plano,")
    print("  igual que la base de datos. Trátalos como tratarías esas contraseñas.")
    print("  Para que queden cifradas en reposo en esta PC, define CPM_SECRET_KEY")
    print("  antes de arrancar; la página Ajustes indica si está activo.")

    if git_managed:
        print("\nPARA ACTUALIZAR MÁS ADELANTE")
        print(f"  cd \"{target}\" && git pull && python install.py --no-browser")
    else:
        print("\nPARA ACTUALIZAR MÁS ADELANTE")
        print("  Esta copia se descargó como zip y no puede hacer `git pull`.")
        print("  Instala git y vuelve a ejecutar install.py en una carpeta nueva.")

    print("\nSI CAMBIAS LA INTERFAZ (web/src)")
    print("  Necesitas Node para recompilarla: cd web && npm install, luego")
    print("  python scripts/build_webui.py, y commitea src/camoufox_pm/webui.")
    print()


# --- main --------------------------------------------------------------------


def default_target() -> Path:
    if IS_WINDOWS:
        # USERPROFILE\Desktop is right for the overwhelming majority; a
        # OneDrive-redirected Desktop is handled by falling back to it.
        home = Path(os.environ.get("USERPROFILE", Path.home()))
        desktop = home / "Desktop"
        if not desktop.is_dir():
            onedrive = Path(os.environ.get("OneDrive", "")) / "Desktop"
            if onedrive.is_dir():
                desktop = onedrive
        return desktop / "Camoufox Persistente"
    return Path.home() / "camoufox-persistente"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instala Camoufox Profile Manager en una PC que solo tiene Python."
    )
    parser.add_argument(
        "--dir", type=Path, default=None,
        help="Carpeta de instalación (por defecto: Escritorio\\Camoufox Persistente)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="No descargar el navegador Camoufox (hazlo luego con: camoufox fetch)",
    )
    parser.add_argument(
        "--no-shortcut", action="store_true",
        help="No crear el acceso directo en el escritorio",
    )
    args = parser.parse_args()

    target = (args.dir or default_target()).expanduser().resolve()

    print("=" * 70)
    print("  Camoufox Profile Manager — instalador")
    print("=" * 70)
    print(f"\nSe instalará en: {target}")

    check_python()
    git_managed = fetch_code(target)
    uv = ensure_uv()
    sync_dependencies(uv, target)

    if args.no_browser:
        step("Omitiendo la descarga del navegador (--no-browser)")
        info("Cuando lo necesites: .venv\\Scripts\\camoufox.exe fetch")
    else:
        fetch_browser(target)

    verify(target)

    # The launcher pins CPM_DB_PATH here; create it so the first run writes to
    # the intended place rather than wherever it was started from.
    (target / "data").mkdir(exist_ok=True)

    shortcut = None
    if IS_WINDOWS and not args.no_shortcut:
        shortcut = create_shortcut(target)

    report(target, shortcut, git_managed)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado. Volver a ejecutar install.py continúa donde quedó.")
        raise SystemExit(130)
