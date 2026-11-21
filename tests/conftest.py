"""В Windows каждому запуску нужен свой доступный временный каталог."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def pytest_configure(config):
    if os.name == "nt" and config.option.basetemp is None:
        workspace = TemporaryDirectory(prefix="sf-test-")
        config.add_cleanup(workspace.cleanup)
        # Pytest очищает basetemp перед запуском. Здесь он владеет только вложенным каталогом.
        config.option.basetemp = str(Path(workspace.name) / "t")
