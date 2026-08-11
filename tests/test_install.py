import os
import shutil
import subprocess
import sys

import pytest
from rich.markup import escape, render

from src.twofas.cli import METHOD_LABELS, is_security_key_set_up
from src.twofas.cli_support import generate_choices
from src.twofas.install import EXTRA_NAME, detect_install_plan, run_install
from src.twofas.keystore import KeyStore, new_wrapped_key, vault_id_for
from src.twofas.unlock import vault_salt

from ._shared import CWD

FILENAME = str(CWD / "2fas-demo-pass.2fas")


def which_for(*available: str):
    return lambda name: name if name in available else None


@pytest.mark.parametrize(
    "prefix,available,manager",
    [
        # a uv-managed tool: --with keeps the dependency across `uv tool upgrade`.
        ("/home/u/.local/share/uv/tools/2fas", ("uv",), "uv tool"),
        # uvenv venvs are uv-managed: the plain-venv uv path covers them.
        ("/home/u/.local/uvenv/venvs/2fas", ("uvenv", "uv"), "uv pip"),
        ("/home/u/.local/uvenv/venvs/2fas", ("uvenv",), "pip"),
        ("/home/u/.local/pipx/venvs/2fas", ("pipx",), "pipx"),
        ("/home/u/.local/share/pipx/venvs/2fas", ("pipx", "uv"), "pipx"),
        # a plain venv: uv can still target this exact interpreter.
        ("/home/u/project/.venv", ("uv",), "uv pip"),
        ("/home/u/project/.venv", (), "pip"),
        # uv/pipx layout but the tool itself is gone: do not propose a command that fails.
        ("/home/u/.local/share/uv/tools/2fas", (), "pip"),
        ("/home/u/.local/pipx/venvs/2fas", (), "pip"),
    ],
)
def test_detect_install_plan(prefix, available, manager):
    plan = detect_install_plan(prefix=prefix, which=which_for(*available))

    assert plan.manager == manager
    assert plan.command[0] != ""
    assert "fido2" in plan.command


def test_install_plan_never_uses_a_shell():
    plan = detect_install_plan(prefix="/home/u/project/.venv", which=which_for())

    assert plan.command[:3] == [sys.executable, "-m", "pip"]
    assert not any(char in " ".join(plan.command) for char in ";|&")


@pytest.fixture(scope="module")
def tool_bin(tmp_path_factory):
    # pipx/uvenv under test are installed fresh, not taken from the developer's machine
    if not shutil.which("uv"):
        pytest.skip("needs uv")

    root = tmp_path_factory.mktemp("tools")
    venv = root / "tools-venv"
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True)
    installed = subprocess.run(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "pipx", "uvenv"],
        check=False,
        capture_output=True,
    )

    if installed.returncode != 0:
        pytest.skip(f"could not install test tools (no network?): {installed.stderr.decode()}")

    return venv / "bin"


@pytest.mark.parametrize(
    "install,venv_path,manager",
    [
        (["uvenv", "install", "2fas"], ".local/uvenv/venvs/2fas", "uv pip"),
        (["uv", "tool", "install", "2fas"], ".local/share/uv/tools/2fas", "uv tool"),
        (["pipx", "install", "2fas"], ".local/share/pipx/venvs/2fas", "pipx"),
        (["uv", "venv", "plain-venv"], "plain-venv", "uv pip"),
    ],
    ids=["uvenv", "uv tool", "pipx", "plain venv"],
)
def test_real_install_flow(tmp_path, monkeypatch, tool_bin, install, venv_path, manager):
    path = f"{tool_bin}{os.pathsep}{os.environ['PATH']}"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("HOME", str(tmp_path))
    env = os.environ | {"HOME": str(tmp_path), "PATH": path}
    installed = subprocess.run(install, env=env, cwd=tmp_path, check=False, capture_output=True)

    if installed.returncode != 0:
        pytest.skip(f"{' '.join(install)} failed (no network?): {installed.stderr.decode()}")

    prefix = tmp_path / venv_path
    python = prefix / "bin" / "python"

    # in production 2fas runs *inside* that venv, so sys.executable points there
    monkeypatch.setattr(sys, "executable", str(python))

    plan = detect_install_plan(prefix=str(prefix))
    assert plan.manager == manager

    # fido2_importable checks the current process; here the install lands in the target venv
    monkeypatch.setattr(
        "src.twofas.install.fido2_importable",
        lambda: subprocess.run([python, "-c", "import fido2"], check=False).returncode == 0,
    )

    assert run_install(plan)


def test_extra_name_survives_rich_markup():
    # `[security-key]` looks like a rich style tag, which silently swallowed it before.
    assert render(escape(EXTRA_NAME)).plain == "2fas[security-key]"
    assert render(EXTRA_NAME).plain != "2fas[security-key]"  # the bug, kept as a regression guard


def test_security_key_gating(tmp_path):
    store = KeyStore(tmp_path / "keys")

    assert not is_security_key_set_up(FILENAME, store)
    assert not is_security_key_set_up("/does/not/exist.2fas", store)

    salt = vault_salt(FILENAME)
    store.put(new_wrapped_key(vault_id_for(salt), b"c", b"s" * 32, b"n" * 12, b"ct", "2fas.local", FILENAME))

    assert is_security_key_set_up(FILENAME, store)


def test_unlock_method_choice_is_disabled_until_set_up():
    labels = {label: value for value, label in METHOD_LABELS.items()}

    not_set_up = generate_choices(labels, with_exit=False, disabled={"security-key": "Set up a security key first"})
    by_value = {choice.value: choice for choice in not_set_up}

    assert by_value["password"].disabled is None
    assert by_value["security-key"].disabled == "Set up a security key first"

    set_up = generate_choices(labels, with_exit=False, disabled={})
    assert all(choice.disabled is None for choice in set_up)
