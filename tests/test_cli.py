from typer.testing import CliRunner

from src.twofas.__about__ import __version__
from src.twofas.cli import app

# click used to mix stdout and stderr and needed `mix_stderr=False` to be told not to.
# Since click 8.2 they are separate by default and the argument no longer exists.
runner = CliRunner()


def test_app():
    result = runner.invoke(app, ["--version"])
    assert __version__ in result.stdout.strip()
