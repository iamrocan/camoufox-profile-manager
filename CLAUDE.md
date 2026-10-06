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
`launch.bat` call `.venv/Scripts/camoufox-pm.exe` directly instead.

## Where the interesting parts are

| | |
|---|---|
| `core/local_proxy.py` | Loopback relay that lets a proxy be switched off while the browser runs. Playwright configures Firefox below the WebExtension layer, so no addon can override its proxy — this is the way around that. |
| `core/fingerprint_store.py` | What gets frozen into a pinned machine and what deliberately does not. Reassembles Camoufox's `CAMOU_CONFIG_*` env chunks; on Windows they are capped at 2047 bytes each and every real-device preset exceeds one chunk. |
| `core/models.py` | `to_camoufox_launch_options()` — the single place where a profile becomes browser arguments. |
| `core/database.py` | Migrations are a list of `(column, definition)` pairs added on startup; existing rows take the default. |
