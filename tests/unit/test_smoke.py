"""The package imports and its version agrees with the installed distribution."""

import re
from importlib.metadata import version

import haynes_studio

# A public PEP 440 version such as 0.1.0, 0.1.0rc1 or 0.1.0.dev0.
PEP440 = re.compile(r"[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?")


def test_package_imports_with_its_version():
    assert PEP440.fullmatch(haynes_studio.__version__)
    assert haynes_studio.__version__ == version("haynes-studio")
