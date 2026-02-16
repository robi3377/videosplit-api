"""initial_schema

Revision ID: 001
Revises: 
Create Date: 2024-12-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=True),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('avatar_url', sa.String(length=500), nullable=True),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('plan_tier', sa.Enum('FREE', 'STARTER', 'PRO', 'ENTERPRISE', name='plantier'), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('subscription_status', sa.String(length=50), nullable=True),
    sa.Column('subscription_ends_at', sa.DateTime(), nullable=True),
    sa.Column('monthly_minutes_limit', sa.Integer(), nullable=False),
    sa.Column('monthly_minutes_used', sa.Integer(), nullable=False),
    sa.Column('last_usage_reset', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_is_admin'), 'users', ['is_admin'], unique=False)
    op.create_index(op.f('ix_users_plan_tier'), 'users', ['plan_tier'], unique=False)
    op.create_index(op.f('ix_users_stripe_customer_id'), 'users', ['stripe_customer_id'], unique=True)
    
    # Create oauth_accounts table
    op.create_table('oauth_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.Enum('GOOGLE', name='oauthprovider'), nullable=False),
    sa.Column('provider_user_id', sa.String(length=255), nullable=False),
    sa.Column('access_token', sa.Text(), nullable=True),
    sa.Column('refresh_token', sa.Text(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    sa.Column('provider_data', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_accounts_id'), 'oauth_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_oauth_accounts_provider'), 'oauth_accounts', ['provider'], unique=False)
    op.create_index(op.f('ix_oauth_accounts_user_id'), 'oauth_accounts', ['user_id'], unique=False)
    
    # Create api_keys table
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('key_hash', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_used', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_id'), 'api_keys', ['id'], unique=False)
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)
    
    # Create usage_logs table
    op.create_table('usage_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=255), nullable=True),
    sa.Column('video_duration_seconds', sa.Float(), nullable=False),
    sa.Column('video_size_mb', sa.Float(), nullable=False),
    sa.Column('segments_count', sa.Integer(), nullable=False),
    sa.Column('processing_time_seconds', sa.Float(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('api_key_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_logs_created_at'), 'usage_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_usage_logs_id'), 'usage_logs', ['id'], unique=False)
    op.create_index(op.f('ix_usage_logs_job_id'), 'usage_logs', ['job_id'], unique=False)
    op.create_index(op.f('ix_usage_logs_user_id'), 'usage_logs', ['user_id'], unique=False)
    
    # Create jobs table
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('original_filename', sa.String(length=500), nullable=False),
    sa.Column('segment_duration', sa.Integer(), nullable=False),
    sa.Column('segments_count', sa.Integer(), nullable=False),
    sa.Column('total_duration', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_created_at'), 'jobs', ['created_at'], unique=False)
    op.create_index(op.f('ix_jobs_id'), 'jobs', ['id'], unique=False)
    op.create_index(op.f('ix_jobs_job_id'), 'jobs', ['job_id'], unique=True)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_job_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_created_at'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_usage_logs_user_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_job_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_id'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_created_at'), table_name='usage_logs')
    op.drop_table('usage_logs')
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_id'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_oauth_accounts_user_id'), table_name='oauth_accounts')
    op.drop_index(op.f('ix_oauth_accounts_provider'), table_name='oauth_accounts')
    op.drop_index(op.f('ix_oauth_accounts_id'), table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
    op.drop_index(op.f('ix_users_stripe_customer_id'), table_name='users')
    op.drop_index(op.f('ix_users_plan_tier'), table_name='users')
    op.drop_index(op.f('ix_users_is_admin'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')