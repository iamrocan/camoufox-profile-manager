# Working on this fork

Notes for anyone — person or Claude Code — picking this up on a machine that
has not seen it before. Claude Code's memory and `.claude/` do not travel:
memory lives outside the repository and `.claude/` is ignored, so anything
worth knowing on the next machine has to be written down here.

This is a fork of [polyackiy/camoufox-profile-manager](https://github.com/polyackiy/camoufox-profile-manager)
with a Spanish/English interface, a per-profile proxy pause, a clear-browser-data
action, a per-profile uBlock toggle, and `install.py`. `origin` is the fork and
`upstream` is the original.

## Setting up

```bash
git clone https://github.com/iamrocan/camoufox-profile-manager.git
cd camoufox-profile-manager
uv sync --extra dev --extra desktop     # dev brings pytest, ruff, mypy
.venv/Scripts/camoufox fetch            # the browser itself, ~200 MB
```

**Python 3.10 to 3.13**, despite `requires-python = ">=3.10"`. `uv.lock` pins
numpy 2.2.6, which camoufox and fpgen both pull in and which ships no wheel for
3.14; uv then tries to build it from source, fails, and leaves the environment
with nothing in it. The app comes up with `No module named 'uvicorn'`, which
names neither Python nor numpy, so it is worth recognising. `install.py` checks
this before downloading anything and `MAX_PYTHON` is where the cap lives --
raise it when the lock moves to a numpy that has the wheels.

Get that Python from python.org, not from `uv python install`: the interpreters
uv downloads are not PSF-signed, and Smart App Control blocks them.

Call the venv's executables directly, not through `uv run`, unless you name the
extras — see the note under Tests for why.

Node is needed **only** to rebuild the interface, and Node 24 is what the
current bundle was built with. `install.py` deliberately does not install it,
because an install that only runs the app does not need it.

The repository has no git identity configured, so commits need one passed in:

```bash
git config user.name  "your-name"
git config user.email "your-email"
```

Do not install into a folder that OneDrive or any other client syncs. The
profile database is SQLite in WAL mode — three files that are only consistent
with each other — and a sync client uploads them whenever it likes. `install.py`
refuses such a folder and explains why.

### `uv sync` failing with os error 396

```
failed to hardlink file ... La operación de nube no se puede realizar en un
archivo con vínculos permanentes incompatibles. (os error 396)
```

That is `ERROR_CLOUD_FILE_INCOMPATIBLE_HARDLINKS`. uv hardlinks from its cache
so one wheel is not stored twice, and a cloud-sync filter driver cannot
represent a hardlink. Add `--link-mode=copy`:

```bash
uv sync --extra dev --extra desktop --link-mode=copy
```

`install.py` detects a synced target, passes the flag, and retries with it when
the first attempt fails anyway, so this only bites a manual sync.

The error comes from Windows' cloud filter driver, but **do not read it as proof
that the folder is synced.** Seen on a machine where it was not: the install
folder and uv's cache both had plain `Directory` attributes, with no
`ReparsePoint`, `Offline` or `RecallOnDataAccess` between them, and `%OneDrive%`
pointed somewhere else entirely. The flag fixed it regardless.

Worth checking anyway, because if a folder *is* synced that is the
WAL-corruption case above and `cloud_root()` can miss it -- it reads the sync
clients' environment variables and folder names rather than asking the
filesystem:

```bash
powershell -Command "(Get-Item .).Attributes; $env:OneDrive"
```

A clean answer there means the folder is fine, not that the error was spurious.

## The committed UI bundle

`src/camoufox_pm/webui/` is **build output that is committed on purpose**, which
upstream does not do. Upstream publishes release wheels that carry it; this fork
is installed by cloning, so a clone without it serves the API and no interface
at all, and rebuilding it needs Node.

So, after changing anything under `web/src`:

```bash
cd web && npx tsc --noEmit -p tsconfig.json && npx eslint src && cd ..
python scripts/build_webui.py
git add src/camoufox_pm/webui   # the bundle is part of the change
```

Forgetting the rebuild ships an interface that silently does not include the
edit. The bundle is marked `-text` in `.gitattributes` so it is checked out byte
for byte and a rebuild does not show up as a diff in line endings alone.

## Restart the server after changing Python

The interface files are read from disk on every request, so a running manager
serves the *new* page while still running the Python it started with. The page
then calls a route the old process has never heard of. Since `28077c6` that
answers 404 and says to restart; before it, the static mount answered 405 and
named the wrong problem entirely.

Changing anything under `src/camoufox_pm/` means closing and reopening the
manager. Changing only `web/src` plus a rebuild does not.

## Smart App Control blocks the console scripts

On Windows 11 with Smart App Control on, `camoufox-pm.exe` and `camoufox.exe`
are blocked: "part of this app has been blocked", or in a console *"Una
directiva de Control de aplicaciones bloqueo este archivo"*, with CodeIntegrity
3033/3077/3118 in the event log. Neither pip nor uv ships those files; they
build them on the machine from a stub, so they are unsigned binaries with no
reputation, which is exactly what SAC vetoes. `python.exe` and `pythonw.exe` in
the same venv are signed by the Python Software Foundation and are allowed.

So nothing here invokes the stubs. `launch.vbs`, `launch.bat` and the shortcut
`install.py` creates all go through the venv's interpreter with
`-m camoufox_pm.cli`, which loads the same code. The shortcut points at
`pythonw.exe` **directly** rather than at `launch.vbs`, because SAC's script
enforcement also reaches Windows Script Host.

Two things follow. SAC's verdict comes from cloud reputation, not from the file,
so it can allow a binary one day and block it the next with nothing changed on
disk -- a launch that worked yesterday and fails today is this, not a
regression. And the shortcut lives on the Desktop, not in the repository, so a
`git pull` fixes the launchers but cannot fix a `.lnk` an older `install.py`
already wrote:

```bash
python install.py --shortcut-only   # repoints the shortcut, installs nothing
```

Do not suggest turning SAC off: it cannot be turned back on without
reinstalling Windows, and the signed route costs nothing.

For a launch that fails for *any* reason, run the diagnostic rather than
guessing, because several unrelated causes look identical from outside:

```bash
powershell -ExecutionPolicy Bypass -File scripts/diagnose.ps1
```

Its section 10 is the one that pays: it starts the server on a spare port, which
separates a server that will not boot from a window that will not open. The
commonest cause of the second is a missing WebView2 runtime, which pywebview
renders in -- the server then works perfectly and only `--desktop` fails.

Check the state with
`(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState`
-- 0 off, 1 blocking, 2 evaluating -- and the signatures with
`Get-AuthenticodeSignature`.

## What the shortcut actually runs

The Desktop shortcut does **not** call the CLI. It calls
`scripts/prelaunch.py` on the venv's `pythonw.exe`, and that calls the CLI:

```
pythonw.exe "<install>\scripts\prelaunch.py" --desktop
```

On **every** launch it fast-forwards the install, then matches the browser to
it, then starts the manager. Arguments it does not recognise are forwarded,
which is how `--desktop` arrives. `launch.vbs` goes the same way; `launch.bat`
deliberately does not, so it stays a launcher that starts the manager and
nothing else.

Nothing is behind an interval. There used to be a daily gate, from when the
browser check hit the GitHub API; the check is local now, and all the gate did
was make a launch that skipped silently look like one that was not checking at
all. That is a real cost: it is indistinguishable from the feature being broken,
and it was reported as such.

**The code update is deliberately timid.** `git pull --ff-only`, and only when
the tree is clean, the branch tracks an upstream, and there are no local commits
on it. A machine being worked on fails several of those and should: this is
allowed to fast-forward an install, not to touch work in progress. Every refusal
says which one it was in `data/prelaunch.log`, because "it did not update" with
no reason given is the thing being fixed here.

The manager starts *after* the pull, which is what makes it take effect -- the
running process reads its Python once, at startup. And when the pull moves
`uv.lock` or `pyproject.toml`, the dependencies are synced before launching: a
pull that adds an import without the package behind it leaves a manager that
will not boot, which is worse than the state before the pull.

The browser is checked **after** the code, on purpose. A pull that moves
camoufox moves the build it pairs with, so asking first would answer about the
version being replaced.

**The target is the paired build, not the newest one.** camoufox stamps each of
its releases with the browser build it was built and tested against --
`camoufox.browser_pin.load_pin()` reads it -- and launching any other build
makes camoufox warn that *"other builds may not be compatible"* and tell you to
run `camoufox set --release`. The fingerprint patches are built against a
particular browser, so an antidetect browser running an untested combination is
the wrong kind of unusual. The browser therefore moves when the *package* moves
(`git pull` plus `uv sync`), and prelaunch keeps the two in step rather than
running ahead of them -- **including moving the browser backwards** to get
there, which is what it did when an earlier version of this chased the newest
stable and left the install two releases ahead of its package.

So "is our browser the latest?" is the wrong question to optimise for. Being
behind the newest release is the normal, intended state.

Three things about it are load-bearing rather than incidental:

**It never blocks the launch.** No network, GitHub rate-limiting the
unauthenticated API, a download that dies halfway: every failure path ends with
the manager opening anyway. The check runs under a timeout because
`list_available_versions` walks three repositories at 20 seconds each, which is
far longer than anyone waits for a window.

**It does not download silently.** `pythonw.exe` has no console and the browser
is a 1.3 GB download; doing that invisibly is indistinguishable from a shortcut
that does nothing, which this project has already lost days to. So when there is
something to fetch, prelaunch re-runs itself with `--run-update` in a **new
console window** that says what is happening and shows camoufox's own progress
bar, and that window launches the manager when it is done.

**It starts the manager detached.** `DETACHED_PROCESS` plus a new process group.
A child sharing its parent's console and job dies when the parent returns --
which it does here, immediately, and the update window closes a few seconds
later. Detaching leaves the manager without a console, so its output goes to
`data/manager.log` instead of at handles that are not there; a shortcut-launched
manager previously logged nowhere at all.

`camoufox set --release` and `camoufox set <repo>/<channel>` **do not download
anything.** They write `config.json` and return; only the form that names a
version reaches the install path, and `fetch` is the half that puts a build on
disk. Worse, it drops `active_version` on
the way through. So `set` alone leaves an install pointing at a build that is
not there -- the app says *"official/stable is not installed"* -- and it leaves
`list_installed()` reporting every build as not-active. `fetch` is the half that
puts a build on disk, and prelaunch runs both, then checks that something is
genuinely active and on disk before believing it worked. An exit code of 0 is
not evidence: that is what the `set`-only version returned while installing
nothing.

Which is why `prune_old_builds()` refuses to delete when no build is marked
active. "Not active" is how a build is marked stale, so that state makes all of
them look stale -- and it deleted every browser on the machine before the guard
existed. It also never removes the last one standing.

Checking it without spending the 1.3 GB:

```bash
python scripts/prelaunch.py --check-only              # report, change nothing
python scripts/prelaunch.py --force-check --dry-run   # whole flow, no download
```

`--no-update` skips the check. `scripts/diagnose.ps1` section 15 prints the tail
of `data/prelaunch.log`, which is the only account of a windowless run.

`--dry-run` proves the window, the forwarding and the launch; it cannot prove
the download, which is the step that broke. Change anything in `update_browser`
and run it for real once.

To put a machine back together after an interrupted or half-done update:

```bash
.venv/Scripts/python.exe -m camoufox fetch
```

**The consequence worth knowing:** updating the browser does not touch pinned
fingerprints, so every profile goes on reporting the Firefox it was created
with. That is what `is_outdated()` and `refresh_browser_version()` are for, and
the Máquina section of each profile offers the one-click fix. Making the update
automatic means profiles now go stale on their own, where before the user moved
browser and pins together.

## Translations

`web/src/lib/i18n.tsx` holds both languages. `en` is the source of truth and
`es` is typed as `Record<MessageKey, string>` against it, so a key added to one
and not the other **fails the type check** rather than rendering a blank label.
That is the point of it; when the build complains about a missing key, add the
translation rather than loosening the type.

Left in English on purpose: proxy, fingerprint, cookies, cache, canvas, WebRTC.
They are the words the field uses, and translating them makes the interface
harder to follow for anyone who reads about this subject anywhere else. Browser
versions, GPU names, timezone identifiers and language tags are data the browser
reports, not interface copy.

## Tests

```bash
uv run --extra dev --extra desktop pytest -q
```

Name both extras. `uv run` re-resolves the environment to match what it is told,
so the bare command would uninstall pytest and pywebview on its way to running
the tests, and `--desktop` would stop working afterwards.

One test is known to fail and did so before any of this fork's changes:
`tests/integration/test_api_profiles.py::test_creating_from_a_preset_pins_that_device`.
It asserts a profile created from a device preset pins that preset's core count
and gets a different one — some presets have no WebGL data, resolution falls
back to a generated fingerprint, and the generated machine is not the preset.
An upstream data gap, not a regression. Everything else passes.

## Two traps worth naming

**Do not write source files with PowerShell `Set-Content`.** It double-converts
UTF-8 and mangles every `—`, `…` and accented character in the file. It silently
corrupted `web/src/app/page.tsx` once. Use an editor, or Python with an explicit
`encoding="utf-8"`. `grep -c "â€"` finds the damage.

**`uv run` re-resolves the environment on every invocation.** That costs seconds
of startup and fails outright with no network, which is why `launch.vbs` and
`launch.bat` call the venv's interpreter directly instead.

## Where the interesting parts are

| | |
|---|---|
| `core/local_proxy.py` | Loopback relay that lets a proxy be switched off while the browser runs. Playwright configures Firefox below the WebExtension layer, so no addon can override its proxy — this is the way around that. |
| `core/fingerprint_store.py` | What gets frozen into a pinned machine and what deliberately does not. Reassembles Camoufox's `CAMOU_CONFIG_*` env chunks; on Windows they are capped at 2047 bytes each and every real-device preset exceeds one chunk. |
| `core/models.py` | `to_camoufox_launch_options()` — the single place where a profile becomes browser arguments. |
| `core/database.py` | Migrations are a list of `(column, definition)` pairs added on startup; existing rows take the default. |
