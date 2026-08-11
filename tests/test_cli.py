from typer.testing import CliRunner

from src.twofas.__about__ import __version__
from src.twofas.cli import app

# by default, click's cli runner mixes stdout and stderr for some reason...
runner = CliRunner()


def test_app():
    result = runner.invoke(app, ["--version"])
    assert __version__ in result.stdout.strip()
