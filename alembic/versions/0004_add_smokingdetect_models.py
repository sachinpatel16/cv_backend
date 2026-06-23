"""add_smokingdetect_models

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-22 02:47:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- smoking_sessions table ---
    op.create_table(
        'smoking_sessions',
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('media_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
        sa.Column('overall_status', sa.String(length=30), nullable=True),
        sa.Column('video_out_path', sa.String(length=512), nullable=True),
        sa.Column('interval', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- smoking_events table ---
    op.create_table(
        'smoking_events',
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('timestamp', sa.Float(), nullable=False),
        sa.Column('person_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cig_detected', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tip_detected', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('smoke_detected', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tip_ratio', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('smoke_area', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('person_box', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('cig_box', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('frame_path', sa.String(length=512), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['smoking_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('smoking_events')
    op.drop_table('smoking_sessions')
