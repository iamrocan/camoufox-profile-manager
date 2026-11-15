"""Explaining the launch Smart App Control refuses.

The whole point of the module is a message someone reads on a bad evening, so
these check the two things that make it useful: that it fires only when SAC is
actually enforcing, and that it carries the marker the interface keys on.
"""

import pytest

from camoufox_pm.core import app_control


@pytest.mark.parametrize("state", [0, 2, None])
def test_says_nothing_when_sac_is_not_enforcing(monkeypatch, state):
    """Off, evaluating, or not a Windows that has it: leave the error alone.

    Worth pinning down. A diagnosis that fires on every failed launch would
    send people to turn off a security feature over a bad proxy.
    """
    monkeypatch.setattr(app_control, "smart_app_control_state", lambda: state)
    assert app_control.explain_launch_failure("Target page closed") is None


def test_explains_the_failure_when_sac_is_enforcing(monkeypatch):
    monkeypatch.setattr(app_control, "smart_app_control_state", lambda: 1)
    message = app_control.explain_launch_failure("Browser closed unexpectedly")

    assert message is not None
    # The interface keys on this to show a translated explanation.
    assert message.startswith(f"{app_control.MARKER}:")
    # The original is kept: this explains a failure, it does not replace the
    # evidence of one.
    assert "Browser closed unexpectedly" in message


def test_names_what_to_do_about_it(monkeypatch):
    """The message has to be actionable, because nothing in the app can fix it.

    SAC has no allowlist, so the only route is the Windows Security toggle --
    and a message that describes the problem without naming that route leaves
    the reader exactly where they started.
    """
    monkeypatch.setattr(app_control, "smart_app_control_state", lambda: 1)
    message = app_control.explain_launch_failure("boom")

    assert "Windows Security" in message
    assert "no allowlist" in message


def test_state_is_read_without_blowing_up_off_windows(monkeypatch):
    """None rather than an exception: this runs inside a launch failure."""
    monkeypatch.setattr(app_control.os, "name", "posix")
    assert app_control.smart_app_control_state() is None
    assert app_control.is_enforcing() is False
