"""add_session_type_to_people_analytics_sessions

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-07 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add session_type column
    op.add_column('people_analytics_sessions', sa.Column('session_type', sa.String(length=50), nullable=True))

    # 2. Populate session_type based on existing video_path subdirectories
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE people_analytics_sessions 
        SET session_type = 'people_analytics' 
        WHERE video_path LIKE '%people_analytics_inputs%'
    """))
    bind.execute(sa.text("""
        UPDATE people_analytics_sessions 
        SET session_type = 'employees' 
        WHERE video_path LIKE '%employee_attendance_inputs%' OR video_path LIKE '%group_photo_%'
    """))
    bind.execute(sa.text("""
        UPDATE people_analytics_sessions 
        SET session_type = 'face_analytics' 
        WHERE video_path LIKE '%face_analytics_inputs%'
    """))
    # Fallback default for any unspecified or gallery-based sessions
    bind.execute(sa.text("""
        UPDATE people_analytics_sessions 
        SET session_type = 'people_analytics' 
        WHERE session_type IS NULL
    """))


def downgrade() -> None:
    # Drop session_type column
    op.drop_column('people_analytics_sessions', 'session_type')
