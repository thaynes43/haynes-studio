"""Report contract examples whose type has no validator as PENDING, never as passed.

A validator test that finds no registered validator records the type in its
user properties. Here that test's status becomes ``pending`` (letter ``P``, word
``PENDING``), the summary line counts it separately, and a closing section lists
every pending type by name.
"""

from __future__ import annotations

import pytest

from tests.contracts.harness import CHECKED, PENDING


def _property(report, name):
    return next((value for key, value in report.user_properties if key == name), None)


def pytest_report_teststatus(report, config):
    if report.when == "call" and report.passed and _property(report, PENDING):
        return "pending", "P", ("PENDING", {"yellow": True})
    return None


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    ran = [
        report for reports in terminalreporter.stats.values() for report in reports
        if getattr(report, "when", None) == "call" and _property(report, CHECKED)
    ]
    if not ran:
        return
    from tests.contracts import harness
    from tests.contracts.registry import VALIDATORS

    examples = [example for path in harness.discover()
                if (example := harness.load(path)[0]) is not None]
    pending = harness.pending_types(VALIDATORS, examples)
    pending_reports = len(terminalreporter.stats.get("pending", []))
    terminalreporter.write_sep("=", "contract validators pending", yellow=bool(pending))
    if not pending:
        terminalreporter.write_line("none: every schema type has a registered validator")
        return
    terminalreporter.write_line(
        f"{len(pending)} schema types have no registered validator; {pending_reports} "
        "examples were checked for shape only and are PENDING, not validated:"
    )
    width = max(len(name) for name, _ in pending)
    for name, count in pending:
        terminalreporter.write_line(f"  {name:<{width}}  {count} example(s)")
