"""add_job_columns_and_auth_tables

Revision ID: 003
Revises: 002
Create Date: 2026-02-18

Adds missing columns to the jobs table:
  - aspect_ratio   VARCHAR(20) nullable
  - crop_position  VARCHAR(20) nullable
  - expires_at     TIMESTAMPTZ nullable, indexed

Note: status column, email_verifications table, and password_resets table
were created by SQLAlchemy create_all at app startup, so this migration
only handles what create_all cannot track (the new columns on an existing table).
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('aspect_ratio', sa.String(20), nullable=True))
    op.add_column('jobs', sa.Column('crop_position', sa.String(20), nullable=True))
    op.add_column('jobs', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_jobs_expires_at', 'jobs', ['expires_at'])

    # ix_jobs_status may already exist from create_all; create only if missing
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'jobs' AND indexname = 'ix_jobs_status'
            ) THEN
                CREATE INDEX ix_jobs_status ON jobs (status);
            END IF;
        END$$;
    """)


def downgrade() -> None:
    op.drop_index('ix_jobs_expires_at', table_name='jobs')
    op.drop_column('jobs', 'expires_at')
    op.drop_column('jobs', 'crop_position')
    op.drop_column('jobs', 'aspect_ratio')
