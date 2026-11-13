"""Read the PoC scripts as data. Nothing here imports or runs ``poc/``: the scripts
parse arguments and call services at import, so tests read their source with ``ast``."""

from __future__ import annotations

import ast
from functools import cache
from typing import Any

from tests.support.policy import REPO_ROOT

POC = REPO_ROOT / "poc"


@cache
def module(name: str) -> ast.Module:
    path = POC / f"{name}.py"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def constants(name: str) -> dict[str, Any]:
    """Module-level ``NAME = <literal>`` assignments (strings, lists, numbers)."""
    found = {}
    for node in module(name).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return found


def function(name: str, func: str) -> ast.FunctionDef:
    for node in module(name).body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node
    raise LookupError(f"poc/{name}.py has no function {func}")


def subprocess_runs(node: ast.AST) -> list[ast.Call]:
    """Every ``subprocess.run(...)`` call inside ``node``, in source order."""
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


def argv(name: str, call: ast.Call, bindings: dict[str, str] | None = None) -> list[str]:
    """The argument vector of a ``subprocess.run`` call: list literals and module-level
    names are resolved; any other expression is looked up in ``bindings`` by its source
    text (for example ``"ledger['id']"``)."""
    known = constants(name)
    bindings = bindings or {}

    def value(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return value(node.left) + value(node.right)
        if isinstance(node, ast.List):
            return [scalar(e) for e in node.elts]
        if isinstance(node, ast.Name) and isinstance(known.get(node.id), list):
            return list(known[node.id])
        raise ValueError(f"unsupported argv expression {ast.unparse(node)}")

    def scalar(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and isinstance(known.get(node.id), str):
            return known[node.id]
        return bindings[ast.unparse(node)]

    return value(call.args[0])


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def statements(node: ast.AST) -> list[str]:
    """The function body's statements as normalized source text."""
    return [ast.unparse(s) for s in node.body if not isinstance(s, ast.Expr)
            or not isinstance(s.value, ast.Constant)]
