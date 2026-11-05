#!/usr/bin/env python3
"""Update the browser, prune the old builds, then open the manager.

Sits between the Desktop shortcut and `camoufox_pm.cli`. The shortcut used to
call the CLI directly; it now calls this, and this calls the CLI.

Three rules shape the whole thing:

**Never block the launch.** An update that cannot happen -- no network, GitHub
rate-limiting the unauthenticated API, a download that dies halfway -- must end
with the manager opening anyway. Every failure path here falls through to the
launch, and the check runs under a timeout because `list_available_versions`
walks three repositories with a 20-second timeout each, which is far longer than
anyone will wait for a window to appear.

**Never work silently where the work is visible.** The shortcut runs
`pythonw.exe`, which has no console, and the browser is a 1.3 GB download: doing
that behind a windowless process is indistinguishable from a shortcut that does
nothing, which is a failure this project has already spent days chasing. So when
there is something to download, this re-runs itself in a **new console window**
that says what is happening and shows camoufox's own progress bar. When there is
nothing to download it stays as silent as before.

**Leave a trail.** Anything on the launch path that can fail quietly needs to be
diagnosable afterwards, so every run appends a line to `data/prelaunch.log` and
`scripts/diagnose.ps1` prints the tail of it.

The check is rate-limited to once every CHECK_EVERY_HOURS so that launching the
app twice in a row does not hit the network twice, and so the usual launch costs
nothing at all.

    --force-check   check now, whatever the last check says
    --check-only    report what it would do, touch nothing, launch nothing
    --no-update     straight to the launch
    --dry-run       go through the whole update flow, download and delete
                    nothing -- for checking the console window on a machine
                    without spending 1.3 GB finding out

Anything else on the command line is passed through to the manager, which is how
the shortcut's `--desktop` gets there.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_DIR / "data" / "prelaunch.json"
LOG_FILE = REPO_DIR / "data" / "prelaunch.log"
MANAGER_LOG = REPO_DIR / "data" / "manager.log"

CHECK_EVERY_HOURS = 24
CHECK_TIMEOUT_SECONDS = 20
LOG_MAX_BYTES = 256 * 1024

# Stable only. A prerelease is not what an unattended update should move someone
# onto, and camoufox publishes them between stable builds.
INCLUDE_PRERELEASE = False

CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

OURS = {"--force-check", "--check-only", "--no-update", "--run-update", "--dry-run"}


# --- plumbing ----------------------------------------------------------------


def trim(path: Path) -> None:
    """Keep a log from growing without end, by dropping its older half."""
    try:
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            tail = path.read_text(encoding="utf-8", errors="replace")[-LOG_MAX_BYTES // 2 :]
            path.write_text(tail, encoding="utf-8")
    except OSError:
        pass


def log(message: str) -> None:
    """Append one line to the launcher's own log."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        trim(LOG_FILE)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")
    except OSError:
        pass  # Logging must never be the reason a launch fails.


def read_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def interpreter(console: bool) -> str:
    """The signed interpreter to use, with or without a console.

    Smart App Control blocks the console scripts pip and uv build on the
    machine, so every route in this project goes through python.exe or
    pythonw.exe, which are signed. See CLAUDE.md.
    """
    exe = Path(sys.executable)
    want = "python.exe" if console else "pythonw.exe"
    if exe.name.lower() != want:
        beside = exe.with_name(want)
        if beside.is_file():
            return str(beside)
    return str(exe)


def due_for_check(state: dict[str, Any]) -> bool:
    last = state.get("last_check")
    if not isinstance(last, (int, float)):
        return True
    return (time.time() - last) >= CHECK_EVERY_HOURS * 3600


# --- the browser -------------------------------------------------------------


def find_update() -> tuple[str, str, int] | None:
    """(installed, available, bytes) when a newer stable build exists.

    Returns None for "nothing to do", including every failure: this runs on the
    launch path, and a check that cannot answer must not stop the app opening.
    """
    try:
        from camoufox.multiversion import get_active_path
        from camoufox.pkgman import Version, list_available_versions
    except Exception as exc:  # noqa: BLE001 - a missing dependency is "no update"
        log(f"check: camoufox no importable ({exc.__class__.__name__})")
        return None

    result: dict[str, Any] = {}

    def probe() -> None:
        try:
            active = get_active_path()
            if active is None:
                result["error"] = "no hay navegador instalado"
                return
            installed = Version.from_path(active)
            available = list_available_versions(include_prerelease=INCLUDE_PRERELEASE)
            if not available:
                result["error"] = "la lista de versiones vino vacia"
                return
            newest = max(available, key=lambda item: item.version)
            result["installed"] = installed.full_string
            result["available"] = newest.version.full_string
            result["size"] = newest.asset_size or 0
            result["newer"] = newest.version > installed
        except Exception as exc:  # noqa: BLE001 - network, API limit, bad data
            result["error"] = f"{exc.__class__.__name__}: {exc}"

    # Bounded because the call underneath walks three repositories with a
    # 20-second timeout each, and nobody waits a minute for a window.
    worker = threading.Thread(target=probe, daemon=True)
    worker.start()
    worker.join(CHECK_TIMEOUT_SECONDS)
    if worker.is_alive():
        log(f"check: sin respuesta en {CHECK_TIMEOUT_SECONDS}s; se abre sin comprobar")
        return None

    if "error" in result:
        log(f"check: {result['error']}")
        return None

    if not result.get("newer"):
        log(f"check: al dia ({result.get('installed')})")
        return None

    return str(result["installed"]), str(result["available"]), int(result["size"])


def update_browser(dry_run: bool = False) -> bool:
    """Move onto the newest stable build, through camoufox's own CLI.

    Driven as a subprocess rather than reimplemented: the CLI already resolves
    the channel, downloads, verifies the sha256 and flips the active version,
    and its progress bar is the thing worth showing in the console window.
    """
    cmd = [interpreter(console=True), "-m", "camoufox", "set", "official/stable"]
    print(f"$ {subprocess.list2cmdline(cmd)}\n", flush=True)
    if dry_run:
        # So the whole console flow can be checked on a machine without
        # spending 1.3 GB on it. Nothing else about the run changes.
        print("--dry-run: no se descarga nada.\n", flush=True)
        log("update: --dry-run, no se ejecuto nada")
        return True
    try:
        code = subprocess.run(cmd, cwd=str(REPO_DIR)).returncode
    except OSError as exc:
        log(f"update: no se pudo ejecutar camoufox set ({exc})")
        return False
    log(f"update: camoufox set termino con codigo {code}")
    return code == 0


def dir_size(path: Path) -> int:
    """Bytes on disk under `path`, as far as it can be read.

    Measured rather than taken from InstalledVersion.asset_size, which is
    GitHub metadata and comes back 0 for builds already on disk -- reporting
    "0.00 GB liberados" after deleting several gigabytes is worse than saying
    nothing. Walking the tree is affordable: it happens once a day at most, and
    always immediately before deleting that same tree.
    """
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def prune_old_builds() -> tuple[int, int]:
    """Remove every installed build except the active one.

    Returns (how many, how many bytes). Each removal is attempted on its own:
    one directory that will not go -- a file still mapped by a browser that has
    not fully exited -- should not keep the others.
    """
    try:
        from camoufox.multiversion import list_installed, remove_version
    except Exception as exc:  # noqa: BLE001
        log(f"prune: camoufox no importable ({exc.__class__.__name__})")
        return 0, 0

    removed = 0
    freed = 0
    try:
        installed = list_installed()
    except Exception as exc:  # noqa: BLE001
        log(f"prune: no se pudo listar ({exc.__class__.__name__}: {exc})")
        return 0, 0

    for build in installed:
        if build.is_active:
            continue
        size = dir_size(build.path)
        try:
            if remove_version(build.path):
                removed += 1
                freed += size
                log(f"prune: borrado {build.path.name}")
        except OSError as exc:
            log(f"prune: no se pudo borrar {build.path.name} ({exc})")
    return removed, freed


# --- launching ---------------------------------------------------------------


def launch_manager(forwarded: list[str]) -> int:
    """Start the manager detached, and return without waiting for it.

    Detached on purpose. This process exits immediately afterwards, and the
    update window closes a few seconds later; a child sharing their console and
    process group goes down with whichever of them is holding it -- observed
    while testing, where the manager died the moment its launcher returned.
    DETACHED_PROCESS plus a new process group puts it out of that lineage, which
    is the state Explorer would have started it in anyway.

    Detaching leaves it with no console, so its output is pointed at a log file
    rather than at handles that are not there: loguru and uvicorn both write to
    stderr, and under `pythonw` that would otherwise go nowhere at all. Which
    also means a manager launched from the shortcut finally keeps a log.

    CPM_DB_PATH is pinned the way launch.vbs pinned it, so the database is the
    one inside the install rather than one relative to wherever this was started
    from, and cwd is set for the same reason.
    """
    env = dict(os.environ)
    env.setdefault("CPM_DB_PATH", str(REPO_DIR / "data" / "profiles.db"))
    cmd = [interpreter(console=False), "-m", "camoufox_pm.cli", *forwarded]
    log(f"launch: {subprocess.list2cmdline(cmd)}")

    stream = None
    try:
        MANAGER_LOG.parent.mkdir(parents=True, exist_ok=True)
        trim(MANAGER_LOG)
        stream = MANAGER_LOG.open("ab")
    except OSError:
        stream = None  # Worth launching without a log; not worth failing over.

    try:
        subprocess.Popen(
            cmd,
            cwd=str(REPO_DIR),
            env=env,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdout=stream or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if stream else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        log(f"launch: FALLO ({exc})")
        return 1
    finally:
        if stream is not None:
            stream.close()
    return 0


def spawn_update_console(forwarded: list[str], dry_run: bool = False) -> int:
    """Re-run this script in a console window, to do the update where it shows."""
    cmd = [interpreter(console=True), str(Path(__file__).resolve()), "--run-update"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += forwarded
    log("update: abriendo consola de actualizacion")
    try:
        subprocess.Popen(cmd, cwd=str(REPO_DIR), creationflags=CREATE_NEW_CONSOLE)
    except OSError as exc:
        # The console is a nicety; the app opening is not.
        log(f"update: no se pudo abrir la consola ({exc}); se abre sin actualizar")
        return launch_manager(forwarded)
    return 0


# --- modes -------------------------------------------------------------------


def run_update_mode(forwarded: list[str], dry_run: bool = False) -> int:
    """What the console window runs: update, prune, then open the manager."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - cosmetic only
        pass

    print("=" * 68)
    print("  Camoufox Profile Manager — actualizando el navegador")
    print("=" * 68)
    print()

    found = find_update()
    if found is None:
        # The window is open, so say why nothing is happening rather than
        # flashing shut and leaving it a mystery.
        print("No hay actualizaciones pendientes, o no se pudo comprobar.")
        print("Se abre la aplicación normalmente.")
        print(f"\nDetalle en: {LOG_FILE}")
    else:
        installed, available, size = found
        print(f"  Versión instalada : {installed}")
        print(f"  Versión nueva     : {available}")
        print(f"  Descarga          : {size / 1e9:.2f} GB")
        print()
        print("No cierres esta ventana. La aplicación se abrirá al terminar.")
        print()

        if update_browser(dry_run=dry_run):
            print("\nNavegador actualizado.")
            removed, freed = (0, 0) if dry_run else prune_old_builds()
            if dry_run:
                print("--dry-run: no se purga ninguna version.")
            if removed:
                print(f"Versiones antiguas eliminadas: {removed} ({freed / 1e9:.2f} GB liberados)")
            print()
            print("AVISO: tus perfiles con fingerprint fijado siguen declarando")
            print(f"       la versión anterior ({installed}). La aplicación los marca")
            print("       en la sección Máquina de cada perfil, con un botón para")
            print("       actualizarlos sin cambiar la máquina.")
        else:
            print("\nLa actualización falló. Se abre la aplicación con la versión actual.")
            print(f"Detalle en: {LOG_FILE}")

    write_state({"last_check": time.time(), "last_check_iso": datetime.now(timezone.utc).isoformat()})

    print("\nAbriendo la aplicación…", flush=True)
    code = launch_manager(forwarded)
    # Long enough to read the notice, short enough not to be in the way.
    time.sleep(6)
    return code


def main() -> int:
    argv = sys.argv[1:]
    flags = {arg for arg in argv if arg in OURS}
    forwarded = [arg for arg in argv if arg not in OURS]

    if "--run-update" in flags:
        return run_update_mode(forwarded, dry_run="--dry-run" in flags)

    if "--check-only" in flags:
        found = find_update()
        if found is None:
            print("Sin actualizaciones pendientes (o no se pudo comprobar).")
            print(f"Ver {LOG_FILE}")
            return 0
        installed, available, size = found
        print(f"Instalada : {installed}")
        print(f"Disponible: {available}")
        print(f"Descarga  : {size / 1e9:.2f} GB")
        try:
            from camoufox.multiversion import list_installed

            stale = [item for item in list_installed() if not item.is_active]
            print(f"Versiones antiguas que se purgarian: {len(stale)}")
        except Exception:  # noqa: BLE001
            pass
        return 0

    state = read_state()

    if "--no-update" in flags:
        log("launch: --no-update")
        return launch_manager(forwarded)

    if not ("--force-check" in flags or due_for_check(state)):
        return launch_manager(forwarded)

    found = find_update()
    state["last_check"] = time.time()
    state["last_check_iso"] = datetime.now(timezone.utc).isoformat()
    write_state(state)

    if found is not None:
        return spawn_update_console(forwarded, dry_run="--dry-run" in flags)

    # Nothing to download. Start the manager first and tidy up behind it, so the
    # pruning costs the user no waiting at all -- it only ever touches builds
    # that are not the active one, so a manager starting up is unaffected.
    code = launch_manager(forwarded)
    prune_old_builds()
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
