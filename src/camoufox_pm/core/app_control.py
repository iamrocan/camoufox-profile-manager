"""Smart App Control, and the launch it will not allow.

Everything else in this project keeps our own code on signed binaries, because
Smart App Control blocks unsigned ones. None of that reaches the browser:
``camoufox.exe`` is a third-party Firefox build and is never signed, so on a
machine with SAC enforcing, launching a profile is refused however well the
manager itself was started.

Nothing here can fix that. SAC has no allowlist and no path exclusions, and the
Defender Antivirus exclusions people reach for are a different mechanism
entirely. The machine has to choose between SAC and this application.

What this module is for is making the refusal legible. Without it the manager
opens, the interface works, the profile list loads, and only the launch fails --
with whatever Playwright says when a process will not start, which names
neither Windows nor the policy. Someone then spends an evening on the parts
that were never broken. The marker below lets the interface say what actually
happened, in the reader's own language.
"""

from __future__ import annotations

import os

from loguru import logger

# Prefix on the launch error, so the web UI can recognise this case and show a
# translated explanation instead of a raw exception. Changing it means changing
# `isAppControlBlock` in web/src/app/page.tsx with it.
MARKER = "SMART_APP_CONTROL"

_POLICY_KEY = r"SYSTEM\CurrentControlSet\Control\CI\Policy"
_POLICY_VALUE = "VerifiedAndReputablePolicyState"


def smart_app_control_state() -> int | None:
    """0 off, 1 enforcing, 2 evaluating. None when it cannot be read.

    None is the ordinary answer on everything that is not a recent Windows:
    the key does not exist, and that is not a failure worth logging loudly.
    """
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _POLICY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _POLICY_VALUE)
        return int(value)
    except (OSError, ValueError, TypeError):
        return None


def is_enforcing() -> bool:
    """Whether SAC is in the state that refuses unsigned binaries."""
    return smart_app_control_state() == 1


def explain_launch_failure(original: str) -> str | None:
    """A better message for a launch that SAC was always going to refuse.

    Returns None when SAC is not enforcing, which leaves the original error
    alone: this should explain the one failure it understands and never
    disguise the others as it.
    """
    if not is_enforcing():
        return None

    logger.warning(
        "Browser launch failed with Smart App Control enforcing; "
        "the browser binary is unsigned and SAC does not allow exceptions"
    )
    return (
        f"{MARKER}: Smart App Control is enforcing on this machine and the "
        "Camoufox browser is an unsigned third-party build, so Windows refuses "
        "to start it. SAC has no allowlist and no path exclusions, so this "
        "cannot be granted per-application: it has to be turned off in Windows "
        "Security > App & browser control > Smart App Control. Since the April "
        "2026 update it can be turned back on there as well. "
        f"(Original error: {original})"
    )
