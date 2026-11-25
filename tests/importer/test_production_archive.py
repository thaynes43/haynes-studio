"""The admin entry point refuses invalid archives before opening a destination."""

import pytest

from haynes_studio.api.key_admin import run
from tests.importer.production_fixture import make_archive


@pytest.mark.parametrize(("damage", "error"), [
    ("proxy", "archive_hash proxy.mp4"),
    ("provenance", "archive_missing wan-service-run.json"),
    ("extra", "archive_extra"),
    ("member_link", "archive_member proxy.mp4"),
    ("directory_link", "archive_directory"),
    ("parent_link", "archive_directory"),
])
def test_archive_refusals(tmp_path, monkeypatch, capsys, damage, error):
    fixture = make_archive(tmp_path / "job")
    dest = tmp_path / "empty-store"
    dest.mkdir()
    proxy = fixture.root / "proxy.mp4"
    if damage == "proxy":
        data = proxy.read_bytes()
        proxy.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    elif damage == "provenance":
        (fixture.root / "wan-service-run.json").unlink()
    elif damage == "extra":
        (fixture.root / "third.mp4").write_bytes(proxy.read_bytes())
    elif damage == "member_link":
        target = tmp_path / "original"
        proxy.rename(target)
        proxy.symlink_to(target)
    elif damage == "directory_link":
        link = tmp_path / "archive-link"
        link.symlink_to(fixture.root, target_is_directory=True)
        fixture.root = link
    elif damage == "parent_link":
        link = tmp_path / "job-link"
        link.symlink_to(fixture.root.parent, target_is_directory=True)
        fixture.root = link / fixture.root.name

    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(dest))
    assert run(fixture.args()) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err.strip() == f"import_production.{error}"
    assert list(dest.iterdir()) == []
