"""Constrain release packages, publications and staging archive ancestry."""

from alembic import op

revision = "0012_release_constraints"
down_revision = "0010_staging_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE publications ADD COLUMN target_id TEXT")
    op.execute("""
        UPDATE publications p SET target_id = pkg.target_id
        FROM release_packages pkg WHERE pkg.sha256 = p.package_sha256
    """)
    duplicate = op.get_bind().exec_driver_sql("""
        SELECT EXISTS (
            SELECT 1 FROM publications
            GROUP BY run_id, target_id HAVING count(*) > 1
        )
    """).scalar_one()
    if duplicate:
        # The migration CLI surfaces ValueError without logging SQL or row data.
        raise ValueError("Cannot apply 0012_release_constraints: multiple publications share a run and target. "
                         "Reconcile the publication history before upgrading.")

    op.execute("""
        ALTER TABLE release_packages
        ADD CONSTRAINT release_packages_document_length CHECK (octet_length(document_bytes) = bytes),
        ADD CONSTRAINT release_packages_run_target_key UNIQUE (sha256, run_id, target_id)
    """)
    op.execute("""
        ALTER TABLE publications
        ALTER COLUMN target_id SET NOT NULL,
        ADD CONSTRAINT publications_run_target_key UNIQUE (run_id, target_id),
        DROP CONSTRAINT publications_package_sha256_fkey,
        ADD CONSTRAINT publications_package_run_target_fkey
            FOREIGN KEY (package_sha256, run_id, target_id)
            REFERENCES release_packages (sha256, run_id, target_id)
    """)
    _constrain_archive_versions()


def _constrain_archive_versions():
    # The archive already requires a parent exactly when number > 1 and makes
    # (record_id, number) unique. A composite FK binds the parent ID to number - 1.
    op.execute("""
        ALTER TABLE archive_versions
        ADD COLUMN parent_number BIGINT GENERATED ALWAYS AS (number - 1) STORED,
        ADD CONSTRAINT archive_versions_identity_number_key UNIQUE (record_id, id, number),
        ADD CONSTRAINT archive_versions_contiguous_parent_fkey
            FOREIGN KEY (record_id, revises_version_id, parent_number)
            REFERENCES archive_versions (record_id, id, number)
    """)
    # Check existence at commit so the API can insert the record before its root.
    op.execute("""
        ALTER TABLE archive_records
        ADD COLUMN root_number BIGINT GENERATED ALWAYS AS (1::bigint) STORED,
        ADD CONSTRAINT archive_records_root_version_fkey
            FOREIGN KEY (id, root_number) REFERENCES archive_versions (record_id, number)
            DEFERRABLE INITIALLY DEFERRED
    """)


def downgrade():
    op.execute("""
        ALTER TABLE archive_records
        DROP CONSTRAINT archive_records_root_version_fkey, DROP COLUMN root_number
    """)
    op.execute("""
        ALTER TABLE archive_versions
        DROP CONSTRAINT archive_versions_contiguous_parent_fkey,
        DROP CONSTRAINT archive_versions_identity_number_key,
        DROP COLUMN parent_number
    """)
    op.execute("""
        ALTER TABLE publications
        DROP CONSTRAINT publications_package_run_target_fkey,
        DROP CONSTRAINT publications_run_target_key,
        ADD CONSTRAINT publications_package_sha256_fkey
            FOREIGN KEY (package_sha256) REFERENCES release_packages (sha256),
        DROP COLUMN target_id
    """)
    op.execute("""
        ALTER TABLE release_packages
        DROP CONSTRAINT release_packages_run_target_key,
        DROP CONSTRAINT release_packages_document_length
    """)
