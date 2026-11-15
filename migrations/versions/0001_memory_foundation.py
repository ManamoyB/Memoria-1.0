"""Initial memory schema. Fresh-database migration only."""

from alembic import op

from migrations.schema_v1 import metadata

revision = "0001_memory_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=True)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_fulltext ON memories "
            "USING gin(to_tsvector('simple', title || ' ' || content))"
        )


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is intentionally disabled; restore an authorized backup"
    )
