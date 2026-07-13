"""add_parameter_based_flags_to_people_analytics_sessions

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-13 12:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('people_analytics_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('track_employees', sa.Boolean(), nullable=False, server_default='true'))
        batch_op.add_column(sa.Column('register_new_visitors', sa.Boolean(), nullable=False, server_default='true'))
        batch_op.add_column(sa.Column('track_repeat_visitors', sa.Boolean(), nullable=False, server_default='true'))
        batch_op.add_column(sa.Column('line_crossing_analysis', sa.Boolean(), nullable=False, server_default='true'))
        batch_op.add_column(sa.Column('track_occupancy', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    with op.batch_alter_table('people_analytics_sessions', schema=None) as batch_op:
        batch_op.drop_column('track_occupancy')
        batch_op.drop_column('line_crossing_analysis')
        batch_op.drop_column('track_repeat_visitors')
        batch_op.drop_column('register_new_visitors')
        batch_op.drop_column('track_employees')
