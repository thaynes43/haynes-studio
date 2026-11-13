"""The package imports and its version agrees with the installed distribution."""

from importlib.metadata import version

from packaging.version import Version

import haynes_studio


def test_package_imports_with_its_version():
    assert Version(haynes_studio.__version__)
    assert haynes_studio.__version__ == version("haynes-studio")
