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


def setup_console() -> None:
    """Make the Windows console able to print the accents in this script.

    A fresh console is on a legacy code page, where every accented character in
    the output arrives as a replacement glyph: an installer whose first line is
    already mangled does not inspire much confidence in the rest. Both halves
    are needed -- the code page so the console can render UTF-8, and the stream
    reconfiguration so Python emits it -- and errors="replace" keeps a console
    that refuses both from turning a cosmetic problem into a crash.
    """
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


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


def run_ok(cmd: list[str], *, cwd: Path | None = None) -> bool:
    """Run a command, show its output, and report whether it worked."""
    info(f"$ {subprocess.list2cmdline(cmd)}")
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None).returncode == 0


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
        warn_if_path_is_long(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # core.longpaths because the committed UI bundle has deeply nested files
        # with hashed names, and without it Windows refuses the checkout at 260
        # characters -- leaving a repo with a .git directory and no working tree.
        clone = [
            git, "-c", "core.longpaths=true",
            "clone", "--depth", "1", REPO_URL, str(target),
        ]
        info(f"$ {subprocess.list2cmdline(clone)}")
        if subprocess.run(clone).returncode != 0:
            # A half-checked-out clone is worse than none: it has a valid .git,
            # so a re-run would take the update path over a broken tree.
            remove_partial(target)
            die(
                "git clone falló",
                hint="Si el error fue 'Filename too long', elige una carpeta con "
                "una ruta más corta con --dir, por ejemplo C:/Camoufox.",
            )
        return True

    step(f"Descargando el repositorio en {target} (git no está instalado)")
    warn(
        "Sin git esta instalación no se puede actualizar con `git pull`. "
        "Para poder actualizarla, instala git y vuelve a ejecutar el script."
    )
    download_zip(target)
    return False


def warn_if_path_is_long(target: Path) -> None:
    """The bundle's longest inner path is ~75 characters below the repo root."""
    headroom = 260 - len(str(target)) - 80
    if headroom < 0:
        warn(
            f"La ruta {target} es larga; en Windows el límite es 260 caracteres "
            "y algunos archivos de la interfaz podrían no caber. Si falla, usa "
            "--dir con una ruta más corta."
        )


def remove_partial(target: Path) -> None:
    if target.exists():
        info(f"Limpiando la instalación incompleta en {target}")
        shutil.rmtree(target, ignore_errors=True)


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
    base = uv + ["sync", "--extra", "desktop"]

    # uv hardlinks from its cache so the same wheel is not stored twice. A
    # cloud-sync filter driver cannot represent a hardlink, and refuses with
    # ERROR_CLOUD_FILE_INCOMPATIBLE_HARDLINKS -- so copy instead when we can
    # already see we are inside one.
    if cloud_root(target):
        info("Carpeta sincronizada en la nube: copiando en vez de enlazar.")
        base += ["--link-mode=copy"]

    if run_ok(base, cwd=target):
        return

    # The filesystem may be unable to hardlink for reasons we cannot see from
    # the path alone -- a mapped drive, or a sync client we do not know about.
    # One retry that cannot hit the problem beats asking the user to diagnose it.
    if "--link-mode=copy" not in base:
        warn("Falló la instalación; reintentando sin enlaces permanentes.")
        if run_ok(base + ["--link-mode=copy"], cwd=target):
            return

    die(
        "uv sync no pudo instalar las dependencias",
        hint="Revisa el error de arriba. Si fue de red, reintenta: volver a "
        "ejecutar install.py continúa donde quedó.",
    )


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


def manager_is_running() -> bool:
    """Whether something is already answering on the manager default port.

    A running manager keeps serving the Python it started with while happily
    serving the *new* interface files off disk, so an update looks applied and
    then fails on the first call to a route the old process never had. Probed
    by connecting rather than by listing processes: the port is what decides
    which code answers.
    """
    import socket

    with socket.socket() as probe:
        probe.settimeout(0.4)
        try:
            return probe.connect_ex(("127.0.0.1", 8000)) == 0
        except OSError:
            return False


def report(target: Path, shortcut: Path | None, git_managed: bool) -> None:
    print("\n" + "=" * 70)
    print("  Instalación terminada")
    print("=" * 70)

    if manager_is_running():
        print()
        print("  >> AVISO: el manager ya está abierto, con el código ANTERIOR.")
        print("     Ciérralo y vuelve a abrirlo, o seguirás viendo la interfaz")
        print("     nueva hablándole a un servidor viejo.")

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
        print("  Cierra el manager primero, luego:")
        print(f'  cd "{target}"')
        print("  python install.py --no-browser")
        print("  Eso trae los cambios y reinstala lo que haga falta. Vuelve a")
        print("  abrir el manager al terminar: el código se carga al arrancar.")
    else:
        print("\nPARA ACTUALIZAR MÁS ADELANTE")
        print("  Esta copia se descargó como zip y no puede hacer `git pull`.")
        print("  Instala git y vuelve a ejecutar install.py en una carpeta nueva.")

    print("\nSI CAMBIAS LA INTERFAZ (web/src)")
    print("  Necesitas Node para recompilarla: cd web && npm install, luego")
    print("  python scripts/build_webui.py, y commitea src/camoufox_pm/webui.")
    print()


# --- main --------------------------------------------------------------------


CLOUD_ENV_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
CLOUD_DIR_NAMES = ("onedrive", "dropbox", "google drive", "googledrive", "icloud drive")


def cloud_root(path: Path) -> Path | None:
    """The cloud-sync folder `path` is inside, if it is inside one.

    Checked by the sync clients' own environment variables first, since those
    are authoritative, then by folder name for the clients that do not set one.
    """
    for var in CLOUD_ENV_VARS:
        value = os.environ.get(var)
        if not value:
            continue
        try:
            root = Path(value).resolve()
            if path == root or path.is_relative_to(root):
                return root
        except (OSError, ValueError):
            continue

    for parent in (path, *path.parents):
        if parent.name.lower() in CLOUD_DIR_NAMES:
            return parent
    return None


def refuse_cloud_folder(target: Path, root: Path, allowed: bool) -> None:
    """Installing into a synced folder corrupts data rather than failing.

    Worth stopping over, because nothing here goes wrong at install time. The
    profile database runs in SQLite's WAL mode, which means three files that are
    only consistent with each other; a sync client uploads them whenever it
    likes, and restoring that set from different moments is how a WAL database
    is corrupted. On top of that every browser profile is thousands of small
    files rewritten constantly, and the proxy passwords are plain text wherever
    CPM_SECRET_KEY is unset -- so this would upload them to someone's cloud.
    """
    warn(f"{target} está dentro de una carpeta sincronizada en la nube ({root}).")
    warn("No es un buen lugar para esta aplicación:")
    warn("  - La base de perfiles es SQLite en modo WAL: son tres archivos que")
    warn("    solo son válidos juntos, y el cliente de sincronización los sube")
    warn("    cuando le toca. Así se corrompe una base WAL.")
    warn("  - Cada perfil son miles de archivos pequeños que cambian sin parar.")
    warn("  - Las contraseñas de proxy están en texto plano si CPM_SECRET_KEY")
    warn("    no está definida, y acabarían subidas a la nube.")

    if allowed:
        warn("Continuando porque se pasó --allow-cloud-folder.")
        return

    warn("")
    warn("Instala en una ruta local, por ejemplo:")
    warn('  python install.py --dir "C:/Camoufox Persistente"')
    warn("El acceso directo se crea igual en el escritorio.")
    warn("Si de verdad lo quieres ahí, añade --allow-cloud-folder.")
    warn("")

    die(
        "instalación cancelada para no poner los datos en la nube",
        hint="instala en una ruta local; mira las sugerencias de arriba",
    )


def default_target() -> Path:
    if IS_WINDOWS:
        home = Path(os.environ.get("USERPROFILE", Path.home()))
        desktop = home / "Desktop"
        if not desktop.is_dir():
            onedrive = Path(os.environ.get("OneDrive", "")) / "Desktop"
            if onedrive.is_dir():
                desktop = onedrive

        # A Desktop that OneDrive has taken over is the common case on a new
        # Windows, and the one place this must not install itself. Fall back to
        # the home folder, which no sync client claims; the shortcut still goes
        # on the Desktop, and a shortcut is a kilobyte.
        candidate = desktop / "Camoufox Persistente"
        if cloud_root(candidate.resolve() if desktop.is_dir() else candidate):
            return home / "Camoufox Persistente"
        return candidate
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
    parser.add_argument(
        "--allow-cloud-folder", action="store_true",
        help="Permitir instalar dentro de OneDrive u otra carpeta sincronizada "
             "(no recomendado: corrompe la base de perfiles)",
    )
    args = parser.parse_args()

    setup_console()
    target = (args.dir or default_target()).expanduser().resolve()

    print("=" * 70)
    print("  Camoufox Profile Manager — instalador")
    print("=" * 70)
    print(f"\nSe instalará en: {target}")

    check_python()

    # Before anything is downloaded: this is about where the data will live, and
    # the answer does not improve after spending ten minutes installing.
    root = cloud_root(target)
    if root:
        step("Comprobando la ubicación elegida")
        refuse_cloud_folder(target, root, args.allow_cloud_folder)

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
