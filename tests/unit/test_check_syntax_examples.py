"""scripts/checks/check_syntax.py parses the JSON under docs/contracts/examples/."""

from __future__ import annotations

import subprocess
import sys

from tests.support.policy import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "checks" / "check_syntax.py"


def _track(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", relative], check=True,
                   capture_output=True)


def test_contract_examples_are_parsed(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    _track(tmp_path, "docs/contracts/examples/valid/good.json", "{}\n")
    _track(tmp_path, "docs/contracts/examples/invalid/bad.json", "{\n")
    _track(tmp_path, "docs/contracts/other.json", "{\n")  # outside the scope
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "docs/contracts/examples/invalid/bad.json: Expecting property name enclosed in "
        "double quotes: line 2 column 1 (char 2)"
    ]
