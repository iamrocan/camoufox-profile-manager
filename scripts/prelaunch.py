#!/usr/bin/env python3
"""Bring the install up to date, match the browser to it, then open the manager.

Sits between the Desktop shortcut and `camoufox_pm.cli`. The shortcut used to
call the CLI directly; it now calls this, and this calls the CLI.

The target is the build the installed camoufox package **pairs with**, not the
newest release. camoufox stamps each of its releases with the browser build it
was built and tested against, and launching another one makes it warn that
"other builds may not be compatible". The fingerprint patches are built against
a particular browser, and an antidetect browser running an untested combination
is the wrong kind of unusual. So the browser moves when the *package* moves --
`git pull` plus `uv sync` -- and this keeps the two in step instead of running
ahead of them. It will move the browser backwards to get there.

Three rules shape the whole thing:

**Never block the launch.** An update that cannot happen -- no network, a
download that dies halfway, a camoufox that cannot be imported -- must end with
the manager opening anyway, and every failure path here falls through to the
launch. Deciding whether an update is needed costs no network at all: the pin is
stamped into the installed package and the installed build is on disk.

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

Two things are checked on **every** launch, because a check that silently skips
itself is indistinguishable from one that is not there:

*The code*, with `git fetch` and a fast-forward pull. The manager is started
afterwards, so a pull takes effect immediately -- which is the whole point, since
the running process is what serves the API and it reads its Python once, at
startup. Only ever fast-forward, only on a clean tree, and never when the branch
is ahead of its upstream: that is a machine with work on it, and this is not
entitled to touch it.

*The browser*, which costs nothing to decide: the pin is stamped into the
installed package and the build is on disk, so it is two local reads. It runs
after the code update on purpose -- a pull that moves camoufox moves the pin with
it, and then the browser that matches is a different one.

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
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_DIR / "data" / "prelaunch.json"
LOG_FILE = REPO_DIR / "data" / "prelaunch.log"
MANAGER_LOG = REPO_DIR / "data" / "manager.log"

# Bounded rather than skipped. A `git fetch` is a second or two online and fails
# fast offline, but a captive portal can hang it, and nobody waits for that to
# find out whether their browser profile manager will open.
GIT_TIMEOUT_SECONDS = 15
SYNC_TIMEOUT_SECONDS = 900
LOG_MAX_BYTES = 256 * 1024

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


# --- the code ----------------------------------------------------------------


def git_exe() -> str | None:
    return shutil.which("git")


def run_git(args: list[str], timeout: int = GIT_TIMEOUT_SECONDS) -> tuple[int, str]:
    """Run a git command in the install and return (code, trimmed output)."""
    git = git_exe()
    if git is None:
        return 127, "git no esta instalado"
    try:
        done = subprocess.run(
            [git, *args],
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} no respondio en {timeout}s"
    except OSError as exc:
        return 126, str(exc)
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def find_code_update() -> int | None:
    """How many commits behind the upstream branch, or None to leave it alone.

    None covers every reason not to pull, and most of them are not failures:
    an install that is not a git clone, a tree with uncommitted changes, a
    branch with local commits on it, no upstream, no network. A developer's
    machine lands in several of those, and should: this is allowed to fast
    forward an install, not to touch work in progress.
    """
    if not (REPO_DIR / ".git").is_dir():
        log("code: la instalacion no es un clon de git; no se actualiza sola")
        return None

    code, out = run_git(["status", "--porcelain"])
    if code != 0:
        log(f"code: git status fallo ({out[:160]})")
        return None
    if out:
        log(f"code: hay cambios sin commitear ({len(out.splitlines())} archivos); no se toca")
        return None

    code, upstream = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if code != 0:
        log("code: la rama no sigue a ninguna remota; no se actualiza sola")
        return None

    code, out = run_git(["fetch", "--quiet"])
    if code != 0:
        log(f"code: git fetch fallo ({out[:160]})")
        return None

    code, counts = run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"])
    if code != 0:
        log(f"code: no se pudo comparar con {upstream} ({counts[:160]})")
        return None
    try:
        ahead_s, behind_s = counts.split()
        ahead, behind = int(ahead_s), int(behind_s)
    except ValueError:
        log(f"code: respuesta inesperada de rev-list ({counts[:80]})")
        return None

    if ahead:
        # Local commits that are not upstream: a machine being worked on.
        log(f"code: {ahead} commit(s) locales sin subir; no se actualiza sola")
        return None
    if not behind:
        log(f"code: al dia con {upstream}")
        return None

    log(f"code: {behind} commit(s) por detras de {upstream}")
    return behind


def update_code() -> bool:
    """Fast-forward the install, and re-sync dependencies if the lock moved.

    Returns whether anything was pulled. Dependency changes matter because the
    manager is about to start: a pull that adds an import without the package
    behind it produces a manager that will not boot, which is a worse state
    than the one before the pull.
    """
    before_code, before = run_git(["rev-parse", "HEAD"])
    cmd = [git_exe() or "git", "pull", "--ff-only"]
    print(f"\n$ {subprocess.list2cmdline(cmd)}\n", flush=True)
    code, out = run_git(["pull", "--ff-only"], timeout=120)
    print(out, flush=True)
    if code != 0:
        log(f"code: git pull fallo ({out[:200]})")
        return False

    after_code, after = run_git(["rev-parse", "HEAD"])
    if before_code or after_code or before == after:
        log("code: pull sin cambios")
        return False
    log(f"code: {before[:8]} -> {after[:8]}")

    changed_code, changed = run_git(["diff", "--name-only", f"{before}..{after}"])
    files = changed.splitlines() if changed_code == 0 else []
    if any(f in ("uv.lock", "pyproject.toml") for f in files):
        print("\nLas dependencias cambiaron. Sincronizando…\n", flush=True)
        sync = [interpreter(console=True), "-m", "uv", "sync", "--extra", "desktop",
                "--link-mode=copy"]
        print(f"$ {subprocess.list2cmdline(sync)}\n", flush=True)
        try:
            rc = subprocess.run(sync, cwd=str(REPO_DIR), timeout=SYNC_TIMEOUT_SECONDS).returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            log(f"code: uv sync no se pudo ejecutar ({exc})")
            print("\nNo se pudieron sincronizar las dependencias.")
            print("Ejecuta a mano:  uv sync --extra desktop --link-mode=copy\n")
            return True
        log(f"code: uv sync termino con codigo {rc}")
        if rc != 0:
            print("\nLa sincronizacion de dependencias fallo.")
            print("Ejecuta a mano:  uv sync --extra desktop --link-mode=copy\n")
    return True


# --- the browser -------------------------------------------------------------


def asset_size_of(full_string: str) -> int:
    """Download size for a build, or 0 when it cannot be looked up.

    Cosmetic -- it fills in a number in the console window. Read from the repo
    cache on disk rather than from the API, so a stale or missing cache costs a
    nicety rather than the update, and the launch path stays off the network.
    """
    try:
        from camoufox.multiversion import load_repo_cache

        for repo in load_repo_cache().get("repos", []):
            for item in repo.get("versions", []):
                if f"{item.get('version')}-{item.get('build')}" == full_string:
                    return int(item.get("asset_size") or 0)
    except Exception:  # noqa: BLE001
        pass
    return 0


def find_update() -> tuple[str, str, int] | None:
    """(installed, paired, bytes) when the browser is not the paired build.

    Answered from the pin stamped into the installed camoufox and from what is
    on disk, so the common case touches no network. Returns None for "nothing
    to do", including every failure: this runs on the launch path, and a check
    that cannot answer must not stop the app opening.
    """
    try:
        from camoufox.browser_pin import load_pin
        from camoufox.multiversion import get_active_path
        from camoufox.pkgman import Version
    except Exception as exc:  # noqa: BLE001 - a missing dependency is "no update"
        log(f"check: camoufox no importable ({exc.__class__.__name__})")
        return None

    try:
        pin = load_pin()
    except Exception as exc:  # noqa: BLE001
        log(f"check: no se pudo leer el emparejamiento ({exc.__class__.__name__})")
        return None

    if pin is None:
        # A development copy of camoufox pairs with nothing, so there is no
        # build to move onto and nothing to decide.
        log("check: esta camoufox no declara build emparejado; nada que hacer")
        return None

    installed = None
    try:
        active = get_active_path()
        if active is not None and active.is_dir():
            installed = Version.from_path(active).full_string
    except Exception as exc:  # noqa: BLE001
        log(f"check: no se pudo leer el build instalado ({exc.__class__.__name__})")

    wanted = f"{pin.version}-{pin.build}"
    if installed == wanted:
        log(f"check: emparejado ({installed})")
        return None

    log(f"check: instalado {installed}, emparejado {wanted}")
    return installed or "ninguno", wanted, asset_size_of(wanted)


def installed_build() -> str | None:
    """The build that is actually on disk and active, or None."""
    try:
        from camoufox.multiversion import get_active_path
        from camoufox.pkgman import Version

        active = get_active_path()
        if active is None or not active.is_dir():
            return None
        return Version.from_path(active).full_string
    except Exception:  # noqa: BLE001 - any failure means "cannot tell"
        return None


def update_browser(dry_run: bool = False) -> bool:
    """Move onto the paired build, through camoufox's own CLI.

    `set --release` drops any explicit choice so the stamped pin decides which
    build is wanted, and `fetch` installs it. Two commands, not one: `set` never
    downloads on its own -- it writes config.json and returns, dropping
    `active_version` on the way, which leaves the install pointing at a build
    that is not there and the app reporting it as "not installed".

    Driven as subprocesses rather than reimplemented: the CLI resolves the
    channel, downloads, verifies the sha256 and flips the active version, and
    its progress bar is the thing worth showing in the console window.

    Returns True only when a build is genuinely installed and active afterwards.
    An exit code of 0 is not enough: that is exactly what the broken one-command
    version returned while leaving nothing installed.
    """
    steps = [
        [interpreter(console=True), "-m", "camoufox", "set", "--release"],
        [interpreter(console=True), "-m", "camoufox", "fetch"],
    ]

    if dry_run:
        for cmd in steps:
            print(f"$ {subprocess.list2cmdline(cmd)}", flush=True)
        print("\n--dry-run: no se descarga nada.\n", flush=True)
        log("update: --dry-run, no se ejecuto nada")
        return True

    for cmd in steps:
        print(f"\n$ {subprocess.list2cmdline(cmd)}\n", flush=True)
        try:
            code = subprocess.run(cmd, cwd=str(REPO_DIR)).returncode
        except OSError as exc:
            log(f"update: no se pudo ejecutar {cmd[3]} ({exc})")
            return False
        log(f"update: camoufox {cmd[3]} termino con codigo {code}")
        if code != 0:
            return False

    landed = installed_build()
    if landed is None:
        log("update: termino sin dejar ningun build activo en disco")
        return False
    log(f"update: activo y en disco: {landed}")
    return True


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

    # The guard that matters. "Not active" is what marks a build for deletion,
    # so a config with no active_version in it makes *every* build look stale --
    # and `camoufox set <repo>/<channel>` removes active_version. Run once in
    # that state and this deletes every browser on the machine, which is exactly
    # what it did before this check existed. No active build, no deleting.
    if not any(build.is_active for build in installed):
        log(f"prune: ninguna version figura como activa ({len(installed)} en disco); no se borra nada")
        return 0, 0

    # Nor the last one standing, whatever the flags say.
    if len(installed) < 2:
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
    print("  Camoufox Profile Manager — actualizando")
    print("=" * 68)

    # Code first, and the browser only afterwards: a pull that moves camoufox
    # moves the build it pairs with, so asking before the pull would answer
    # about the version being replaced.
    behind = find_code_update()
    if behind:
        print(f"\n  Hay {behind} actualización(es) de la aplicación. Descargando…")
        if dry_run:
            print("  --dry-run: no se actualiza el código.")
        elif update_code():
            print("\n  Aplicación actualizada.")

    print()
    found = find_update()
    if found is None:
        # The window is open, so say why nothing is happening rather than
        # flashing shut and leaving it a mystery.
        print("El navegador ya es el que corresponde a esta versión.")
        print("Se abre la aplicación normalmente.")
        print(f"\nDetalle en: {LOG_FILE}")
    else:
        installed, wanted, size = found
        print(f"  Versión instalada  : {installed}")
        print(f"  Versión emparejada : {wanted}")
        if size:
            print(f"  Descarga           : {size / 1e9:.2f} GB")
        print()
        print("Esa es la versión con la que esta camoufox fue construida y probada.")
        print("No es necesariamente la más nueva, y esa es justamente la idea.")
        print()
        print("No cierres esta ventana. La aplicación se abrirá al terminar.")
        print()

        if update_browser(dry_run=dry_run):
            print("\nNavegador ajustado.")
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
            print("\nNo se pudo ajustar. Se abre la aplicación con la versión actual.")
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
        behind = find_code_update()
        print(f"Codigo     : {behind} commit(s) por detras" if behind else "Codigo     : al dia (o no actualizable; ver el log)")
        found = find_update()
        if found is None:
            print("Navegador  : emparejado")
            print(f"Ver {LOG_FILE}")
            return 0
        installed, wanted, size = found
        print(f"Instalada  : {installed}")
        print(f"Emparejada : {wanted}")
        print(f"Descarga   : {size / 1e9:.2f} GB")
        try:
            from camoufox.multiversion import list_installed

            stale = [item for item in list_installed() if not item.is_active]
            print(f"Versiones antiguas que se purgarian: {len(stale)}")
        except Exception:  # noqa: BLE001
            pass
        return 0

    if "--no-update" in flags:
        log("launch: --no-update")
        return launch_manager(forwarded)

    state = read_state()
    state["last_check"] = time.time()
    state["last_check_iso"] = datetime.now(timezone.utc).isoformat()
    write_state(state)

    # Both on every launch. The browser comparison is two local reads; the code
    # one is a bounded fetch. Neither is gated behind an interval any more --
    # the old daily gate came from a check that hit the GitHub API, and all it
    # does now is make a launch that skipped silently look like one that is not
    # checking at all.
    behind = find_code_update()
    found = None if behind else find_update()

    if behind or found is not None:
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
