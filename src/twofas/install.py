"""
This file works out how to add the optional `fido2` dependency to *this* installation.

Telling someone to `pip install '2fas[yubikey]'` is unhelpful when they installed 2fas with
pipx or as a uv tool: plain pip either fails or installs into the wrong environment. So we
look at where we are actually running from and propose the command that fits, preferring uv
where it is available.
"""

import importlib
import shutil
import subprocess  # nosec: B404 - only ever run with an argument list, never a shell
import sys
import typing
from pathlib import Path

EXTRA_PACKAGE = "fido2"
EXTRA_NAME = "2fas[yubikey]"


class InstallPlan(typing.NamedTuple):
    """
    How to add `fido2` to the environment 2fas is running in.
    """

    command: list[str]
    manager: str

    def as_shell(self) -> str:
        """
        The command as you would type it, for printing.
        """
        return " ".join(self.command)


def _looks_like(prefix: Path, *needles: str) -> bool:
    parts = set(prefix.parts)
    return all(needle in parts for needle in needles)


def detect_install_plan(prefix: str = None, which: typing.Callable[[str], str | None] = None) -> InstallPlan:
    """
    Work out which package manager owns this installation.

    Args:
        prefix: sys.prefix override, for tests.
        which: shutil.which override, for tests.

    Returns:
        the command to run, plus a human-readable name for the manager it belongs to.
    """
    resolved = Path(prefix or sys.prefix).resolve()
    which = which or shutil.which

    # a uv-managed tool: `--with` is the persistent way to add a dependency, so it
    # survives `uv tool upgrade`. Injecting into the venv by hand would not.
    if _looks_like(resolved, "uv", "tools") and which("uv"):
        return InstallPlan(["uv", "tool", "install", "--with", EXTRA_PACKAGE, "2fas"], "uv tool")

    if _looks_like(resolved, "pipx") and which("pipx"):
        return InstallPlan(["pipx", "inject", "2fas", EXTRA_PACKAGE], "pipx")

    # a plain venv (or anything else): uv pip can target this exact interpreter.
    if which("uv"):
        return InstallPlan(["uv", "pip", "install", "--python", sys.executable, EXTRA_PACKAGE], "uv pip")

    return InstallPlan([sys.executable, "-m", "pip", "install", EXTRA_PACKAGE], "pip")


def fido2_importable() -> bool:
    """
    Whether `fido2` can be imported right now, ignoring anything cached from before.
    """
    importlib.invalidate_caches()
    try:
        importlib.import_module(EXTRA_PACKAGE)
    except ImportError:
        return False

    return True


def run_install(plan: InstallPlan) -> bool:
    """
    Run an install plan and report whether `fido2` became importable.

    Never goes through a shell.
    """
    try:
        completed = subprocess.run(plan.command, check=False)  # nosec: B603 - fixed argument list
    except OSError as e:
        print(f"Could not run {plan.as_shell()}: {e}", file=sys.stderr)
        return False

    if completed.returncode != 0:
        return False

    return fido2_importable()
