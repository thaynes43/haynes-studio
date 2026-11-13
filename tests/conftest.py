"""Shared pytest setup. The policy (limits, markers, db and live gating, checkout
guard, redaction) and its fixtures live in tests/support/plugin.py."""

pytest_plugins = ["pytester", "tests.support.plugin"]
