"""Dark Reader, for the half of dark mode a preference cannot do.

``color_scheme="dark"`` tells a site the user prefers a dark theme, which only
helps on a site that *has* one. Everything else stays as light as it was, and
"dark mode" meaning "most of the web, sometimes" is not what anyone asks for.
Dark Reader recolours the page itself, so a site with no dark theme gets one.

Fetched from addons.mozilla.org on first use and cached in Camoufox's shared
addons directory, which is exactly how Camoufox handles the uBlock Origin it
ships -- same directory, same download-and-extract helpers, same "already
extracted" check. Nothing is vendored into this repository.

The cost is real and worth stating: this is a second extension in the browser,
it is visible to a page that goes looking, and it changes what every page
renders. That is the trade this makes in exchange for actually being dark, and
it is why it rides on a per-profile switch rather than being always on.
"""

from __future__ import annotations

import os

from loguru import logger

# The AMO "latest" endpoint, the same form Camoufox uses for uBlock Origin, so
# the extension tracks its own releases rather than a version pinned in here.
DARK_READER_XPI = "https://addons.mozilla.org/firefox/downloads/latest/darkreader/latest.xpi"
ADDON_NAME = "DARKREADER"

_failed = False


def ensure_dark_reader() -> str | None:
    """Path to the extracted extension, or None if it cannot be had.

    None is an ordinary answer, not an error: no network on a first launch, a
    download that dies, a Camoufox too old to expose the helpers. The caller
    falls back to the colour-scheme preference alone, which is worse than the
    full thing and much better than refusing to start the browser.

    Once a download has failed in this process it is not retried, so a machine
    that is offline pays the timeout once rather than on every launch.
    """
    global _failed
    if _failed:
        return None

    try:
        from camoufox.addons import ADDONS_DIR, download_and_extract
    except ImportError:  # pragma: no cover - only without camoufox installed
        return None

    path = str(ADDONS_DIR / ADDON_NAME)
    manifest = os.path.join(path, "manifest.json")

    # A bare directory is not enough: a failed download leaves one behind, and
    # Camoufox's own confirm_paths() rejects an addon without its manifest.
    if os.path.exists(manifest):
        return path

    try:
        os.makedirs(path, exist_ok=True)
        logger.info("Downloading Dark Reader (first launch with dark mode on)")
        download_and_extract(DARK_READER_XPI, path, ADDON_NAME)
    except Exception as exc:  # noqa: BLE001 - never block a launch over this
        import shutil

        # Drop the partial directory so the next launch re-downloads rather
        # than finding a directory that looks installed and is not.
        shutil.rmtree(path, ignore_errors=True)
        _failed = True
        logger.warning(f"Could not install Dark Reader, dark mode will be preference-only: {exc}")
        return None

    if not os.path.exists(manifest):
        _failed = True
        logger.warning("Dark Reader extracted without a manifest; ignoring it")
        return None

    logger.info(f"Dark Reader ready at {path}")
    return path
