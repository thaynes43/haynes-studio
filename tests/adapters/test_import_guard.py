"""Importing any package module runs no process, opens no socket, parses no arguments
and reads no environment.

Each check imports the modules in a fresh interpreter (``python -I`` with an empty
environment), so nothing is already cached. The modules' own outside imports (standard
library and third party) load first; then the guards go in and every module of the
package is imported under them. ``haynes_studio.__main__`` is skipped: it is the
``python -m haynes_studio`` entry point, and running the command is what importing it
means. A second check proves the guards catch each kind of side effect.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

GUARD = textwrap.dedent(r'''
    import argparse, ast, importlib, importlib.util, json, os, pathlib, socket, subprocess, sys
    package, skip, extra = sys.argv[1], set(filter(None, sys.argv[2].split(','))), sys.argv[3]
    if extra:
        sys.path.insert(0, extra)
    root = pathlib.Path(importlib.util.find_spec(package).submodule_search_locations[0])
    modules, outside = [], set()
    for path in sorted(root.rglob('*.py')):
        parts = path.relative_to(root).with_suffix('').parts
        if not all(p.isidentifier() for p in parts):
            continue  # not importable: the pinned in-pod snippets live in pinned-inputs/
        name = '.'.join((package,) + tuple(p for p in parts if p != '__init__'))
        modules.append(name)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                outside.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                outside.add(node.module)
    for name in sorted(n for n in outside if n.split('.')[0] != package):
        importlib.import_module(name)

    def refuse(what):
        def guard(*args, **kwargs):
            raise RuntimeError('import-time ' + what)
        return guard

    class NoEnv:
        def __getattr__(self, name):
            raise RuntimeError('import-time environment read')
        __getitem__ = __contains__ = __iter__ = __len__ = refuse('environment read')

    class NoArgv(list):
        __getitem__ = __iter__ = __len__ = __contains__ = refuse('sys.argv read')

    saved = {}
    def patch(owner, name, value):
        if hasattr(owner, name):
            saved[(owner, name)] = getattr(owner, name)
            setattr(owner, name, value)
    patch(os, 'environ', NoEnv()); patch(os, 'environb', NoEnv())
    patch(sys, 'argv', NoArgv())
    patch(subprocess.Popen, '__init__', refuse('subprocess'))
    for name in ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv',
                 'execve', 'execvp', 'execvpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe'):
        patch(os, name, refuse('process start'))
    for name in ('parse_args', 'parse_known_args', 'parse_intermixed_args',
                 'parse_known_intermixed_args'):
        patch(argparse.ArgumentParser, name, refuse('argument parsing'))
    patch(socket.socket, 'connect', refuse('socket connect'))
    patch(socket, 'create_connection', refuse('socket connect'))

    failures, imported = {}, []
    for name in modules:
        if name in skip:
            continue
        try:
            importlib.import_module(name)
            imported.append(name)
        except BaseException as error:
            failures[name] = type(error).__name__ + ': ' + str(error)[:200]
    for (owner, name), value in saved.items():
        setattr(owner, name, value)
    print(json.dumps({'imported': imported, 'failures': failures}))
''')


def guarded_import(package: str, skip: str = "", extra_path: str = "") -> dict:
    result = subprocess.run([sys.executable, "-I", "-c", GUARD, package, skip, extra_path],
                            capture_output=True, env={}, timeout=120, check=False)
    assert result.returncode == 0, result.stderr.decode()[-2000:]
    return json.loads(result.stdout)


def test_every_package_module_imports_without_side_effects():
    outcome = guarded_import("haynes_studio", skip="haynes_studio.__main__")
    assert outcome["failures"] == {}
    adapters = {m for m in outcome["imported"] if m.startswith("haynes_studio.adapters")}
    assert adapters >= {
        "haynes_studio.adapters", "haynes_studio.adapters.runner", "haynes_studio.adapters.pinned",
        "haynes_studio.adapters.kokoro", "haynes_studio.adapters.whisper",
        "haynes_studio.adapters.comfyui", "haynes_studio.adapters.wan_ledger",
        "haynes_studio.adapters.fakes", "haynes_studio.adapters.recovery",
        "haynes_studio.adapters.errors", "haynes_studio.adapters.wan"}
    assert "haynes_studio.cli" in outcome["imported"]


def test_the_guards_catch_each_side_effect(tmp_path):
    package = tmp_path / "guardprobe"
    package.mkdir()
    (package / "__init__.py").write_text("")
    probes = {
        "reads_env": "import os\nHOME = os.environ.get('HOME')\n",
        "getenv": "import os\nHOME = os.getenv('HOME')\n",
        "runs_process": "import subprocess\nsubprocess.run(['true'])\n",
        "parses_args": "import argparse\nargparse.ArgumentParser(prog='x').parse_args()\n",
        "reads_argv": "import sys\nFIRST = sys.argv[0]\n",
        "connects": "import socket\nsocket.create_connection(('127.0.0.1', 9))\n",
        "clean": "import json\nVALUE = json.dumps({})\n",
    }
    for name, source in probes.items():
        (package / f"{name}.py").write_text(source)
    outcome = guarded_import("guardprobe", extra_path=str(tmp_path))
    assert set(outcome["failures"]) == {f"guardprobe.{n}" for n in probes if n != "clean"}
    assert "guardprobe.clean" in outcome["imported"]
    assert all("import-time" in text for text in outcome["failures"].values())
