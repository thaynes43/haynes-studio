"""Keep the operator's runtime GRANT reference in sync with Alembic."""

import re
import runpy
from pathlib import Path
from shutil import copyfile

from alembic.script import ScriptDirectory

from haynes_studio.db.grants import RUNTIME_GRANTS

REFERENCES = Path(__file__).resolve().parents[2] / "docs/reference"
MIGRATIONS = REFERENCES.parents[1] / "src/haynes_studio/db/migrations"


def _table_privileges(grants):
    entries = set()
    for privileges, tables in grants:
        names = re.findall(r"[A-Z]+(?: \([^()]+\))?", privileges)
        assert ", ".join(names) == privileges
        for name in names:
            privilege, _, columns = name.partition(" (")
            fields = tuple(sorted(columns.rstrip(")").split(", "))) if columns else ()
            entries.update((table, privilege, fields) for table in tables)
    return entries


def test_documented_runtime_table_grants_match_alembic():
    reference = REFERENCES / "studio-api.md"
    sql = reference.read_text(encoding="utf-8").split("```sql\n", 1)[1].split("```", 1)[0]
    documented = []
    for statement in sql.split(";"):
        statement = " ".join(line.strip() for line in statement.splitlines()
                             if not line.lstrip().startswith("--")).strip()
        if not statement or statement.startswith(("GRANT USAGE ON SCHEMA ", "GRANT CONNECT ON DATABASE ")):
            continue
        grant = re.fullmatch(r"GRANT (.+?) ON (.+) TO studio_app", " ".join(statement.split()))
        assert grant, statement
        privileges, tables = grant.groups()
        names = tables.split(", ")
        assert all(re.fullmatch(r"studio\.[a-z_][a-z_0-9]*", name) for name in names)
        documented.append((privileges, tuple(name.removeprefix("studio.") for name in names)))

    assert _table_privileges(documented) == _table_privileges(RUNTIME_GRANTS)


def test_migration_chain_follows_go_live_job_operations_and_format_recipes(tmp_path):
    versions = MIGRATIONS / "versions"
    escalation = versions / "0007_escalation_packages.py"
    declaration = runpy.run_path(str(escalation))
    assert declaration["revision"] == "0007_escalation_packages"
    assert declaration["down_revision"] == "0006_format_recipes"
    if (versions / "0006_format_recipes.py").is_file():
        migrations = ScriptDirectory(str(MIGRATIONS))
        assert migrations.get_revision("0006_format_recipes").down_revision == "0005_job_operations"
    else:
        # PR 105 can land independently. Until then, verify the present
        # prefix here and exercise the full chain in the database suite.
        prefix = tmp_path / "versions"
        prefix.mkdir()
        for file in versions.glob("*.py"):
            if file != escalation:
                copyfile(file, prefix / file.name)
        migrations = ScriptDirectory(str(tmp_path))
    assert len(migrations.get_heads()) == 1
    assert migrations.get_revision("0005_job_operations").down_revision == "0004_go_live_approvals"


def test_agent_key_terminal_output_guidance_covers_pod_logs():
    for reference in ("studio-api.md", "studio-mcp.md"):
        prose = " ".join((REFERENCES / reference).read_text(encoding="utf-8").split())
        assert "Use `create` without `--out` only from an interactive `kubectl exec`." in prose, reference
        assert "logged by Kubernetes even with a TTY" in prose, reference
