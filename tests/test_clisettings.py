import tempfile
from pathlib import Path

import pytest
from configuraptor.errors import ConfigErrorExtraKey

from src.twofas.cli_settings import get_cli_setting, load_cli_settings, set_cli_setting


@pytest.fixture
def empty_temp_config():
    with tempfile.NamedTemporaryFile(suffix=".toml") as f:
        yield Path(f.name)


EXAMPLE_CONFIG = """
[tool.2fas]
files = ["a", "b"]
default_file = "a"
"""


@pytest.fixture
def filled_temp_config(empty_temp_config):
    empty_temp_config.write_text(EXAMPLE_CONFIG)
    yield empty_temp_config


def test_missing():
    settings = load_cli_settings("/tmp/2fas-test-missing.toml")

    assert not settings.files
    assert not settings.default_file


def test_empty(empty_temp_config):
    settings = load_cli_settings(empty_temp_config)

    assert not settings.files
    assert not settings.default_file


def test_overwrite_empty(empty_temp_config):
    settings = load_cli_settings(empty_temp_config, files=["1", "2"], default_file="1")

    assert settings.files == ["1", "2"]
    assert settings.default_file == "1"


def test_filled(filled_temp_config):
    settings = load_cli_settings(filled_temp_config)
    assert settings.files == ["a", "b"]
    assert settings.default_file == "a"


def test_overwrite_filled(filled_temp_config):
    settings = load_cli_settings(filled_temp_config, files=["1", "2"], default_file="1")

    assert settings.files == ["1", "2"]
    assert settings.default_file == "1"


def test_get_setting(filled_temp_config):
    assert (
        get_cli_setting("default_file", filled_temp_config)
        == get_cli_setting("default-file", filled_temp_config)
        == "a"
    )

    with pytest.raises(AttributeError):
        assert not get_cli_setting("nothing")


def test_set_setting(filled_temp_config):
    set_cli_setting("default-file", "x", filled_temp_config)

    assert get_cli_setting("default_file", filled_temp_config) == "x"

    with pytest.raises(ConfigErrorExtraKey):
        set_cli_setting("nothing", "else matters")
