"""create_gallery_and_refactor_media

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-07 06:32:42.027505

"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create gallery_media table
    op.create_table('gallery_media',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('filepath', sa.String(length=512), nullable=False),
    sa.Column('processed_filepath', sa.String(length=512), nullable=True),
    sa.Column('media_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_delete', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('update_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    bind = op.get_bind()

    # 2. Migrate existing activity_media to gallery_media
    has_activity_media = bind.execute(sa.text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'activity_media')")).scalar()
    if has_activity_media:
        bind.execute(sa.text("""
            INSERT INTO gallery_media (id, tenant_id, filename, filepath, processed_filepath, media_type, status, is_active, is_delete, created_at, update_at)
            SELECT id, tenant_id, filename, filepath, output_filepath, media_type, status, is_active, is_delete, created_at, update_at
            FROM activity_media
        """))

    # 3. Add gallery_media_id column to activity_alerts as nullable first
    op.add_column('activity_alerts', sa.Column('gallery_media_id', sa.Uuid(), nullable=True))
    # Map from activity_media_id
    if has_activity_media:
        bind.execute(sa.text("UPDATE activity_alerts SET gallery_media_id = activity_media_id"))
    # Drop foreign key constraint
    op.drop_constraint('activity_alerts_activity_media_id_fkey', 'activity_alerts', type_='foreignkey')
    # Drop old column
    op.drop_column('activity_alerts', 'activity_media_id')
    # Alter new column to NOT NULL
    op.alter_column('activity_alerts', 'gallery_media_id', nullable=False)
    # Create new foreign key
    op.create_foreign_key(None, 'activity_alerts', 'gallery_media', ['gallery_media_id'], ['id'], ondelete='CASCADE')

    # 4. Add gallery_media_id column to activity_configs as nullable first
    op.add_column('activity_configs', sa.Column('gallery_media_id', sa.Uuid(), nullable=True))
    # Map from activity_media_id
    if has_activity_media:
        bind.execute(sa.text("UPDATE activity_configs SET gallery_media_id = activity_media_id"))
    # Drop foreign key constraint
    op.drop_constraint('activity_configs_activity_media_id_fkey', 'activity_configs', type_='foreignkey')
    # Drop old column
    op.drop_column('activity_configs', 'activity_media_id')
    # Alter new column to NOT NULL
    op.alter_column('activity_configs', 'gallery_media_id', nullable=False)
    # Create new foreign key
    op.create_foreign_key(None, 'activity_configs', 'gallery_media', ['gallery_media_id'], ['id'], ondelete='CASCADE')

    # 5. Drop activity_media table
    if has_activity_media:
        op.drop_table('activity_media')

    # 6. Add gallery_media_id column to object_count_media as nullable first
    op.add_column('object_count_media', sa.Column('gallery_media_id', sa.Uuid(), nullable=True))
    # For each row, generate a new gallery_media item and point to it
    rows_oc = bind.execute(sa.text("SELECT id, tenant_id, filename, filepath, processed_filepath, media_type, status, created_at, update_at FROM object_count_media")).fetchall()
    for row in rows_oc:
        g_id = uuid.uuid4()
        bind.execute(
            sa.text("""
                INSERT INTO gallery_media (id, tenant_id, filename, filepath, processed_filepath, media_type, status, created_at, update_at)
                VALUES (:id, :tenant_id, :filename, :filepath, :processed_filepath, :media_type, :status, :created_at, :update_at)
            """),
            {"id": g_id, "tenant_id": row.tenant_id, "filename": row.filename, "filepath": row.filepath, "processed_filepath": row.processed_filepath, "media_type": row.media_type, "status": row.status, "created_at": row.created_at, "update_at": row.update_at}
        )
        bind.execute(
            sa.text("UPDATE object_count_media SET gallery_media_id = :g_id WHERE id = :id"),
            {"g_id": g_id, "id": row.id}
        )
    # Alter new column to NOT NULL
    op.alter_column('object_count_media', 'gallery_media_id', nullable=False)
    # Create new foreign key
    op.create_foreign_key(None, 'object_count_media', 'gallery_media', ['gallery_media_id'], ['id'], ondelete='CASCADE')
    # Drop old file columns from object_count_media
    op.drop_column('object_count_media', 'media_type')
    op.drop_column('object_count_media', 'filename')
    op.drop_column('object_count_media', 'filepath')
    op.drop_column('object_count_media', 'processed_filepath')

    # 7. Add gallery_media_id column to people_count_media as nullable first
    op.add_column('people_count_media', sa.Column('gallery_media_id', sa.Uuid(), nullable=True))
    # For each row, generate a new gallery_media item and point to it
    rows_pc = bind.execute(sa.text("SELECT id, tenant_id, filename, filepath, processed_filepath, media_type, status, created_at, update_at FROM people_count_media")).fetchall()
    for row in rows_pc:
        g_id = uuid.uuid4()
        bind.execute(
            sa.text("""
                INSERT INTO gallery_media (id, tenant_id, filename, filepath, processed_filepath, media_type, status, created_at, update_at)
                VALUES (:id, :tenant_id, :filename, :filepath, :processed_filepath, :media_type, :status, :created_at, :update_at)
            """),
            {"id": g_id, "tenant_id": row.tenant_id, "filename": row.filename, "filepath": row.filepath, "processed_filepath": row.processed_filepath, "media_type": row.media_type, "status": row.status, "created_at": row.created_at, "update_at": row.update_at}
        )
        bind.execute(
            sa.text("UPDATE people_count_media SET gallery_media_id = :g_id WHERE id = :id"),
            {"g_id": g_id, "id": row.id}
        )
    # Alter new column to NOT NULL
    op.alter_column('people_count_media', 'gallery_media_id', nullable=False)
    # Create new foreign key
    op.create_foreign_key(None, 'people_count_media', 'gallery_media', ['gallery_media_id'], ['id'], ondelete='CASCADE')
    # Drop old file columns from people_count_media
    op.drop_column('people_count_media', 'media_type')
    op.drop_column('people_count_media', 'filename')
    op.drop_column('people_count_media', 'filepath')
    op.drop_column('people_count_media', 'processed_filepath')

    # 8. Add gallery_media_id column to smoking_sessions as nullable
    op.add_column('smoking_sessions', sa.Column('gallery_media_id', sa.Uuid(), nullable=True))
    # Create new foreign key
    op.create_foreign_key(None, 'smoking_sessions', 'gallery_media', ['gallery_media_id'], ['id'], ondelete='SET NULL')
    # Drop old media_id
    op.drop_column('smoking_sessions', 'media_id')


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('activity_media',
    sa.Column('tenant_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('filename', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
    sa.Column('filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=False),
    sa.Column('media_type', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
    sa.Column('is_delete', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('update_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('output_filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('activity_media_pkey'))
    )

    with op.batch_alter_table('smoking_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('media_id', sa.UUID(), autoincrement=False, nullable=True))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('gallery_media_id')

    with op.batch_alter_table('people_count_media', schema=None) as batch_op:
        batch_op.add_column(sa.Column('processed_filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=True))
        batch_op.add_column(sa.Column('filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('filename', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('media_type', sa.VARCHAR(length=20), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('gallery_media_id')

    with op.batch_alter_table('object_count_media', schema=None) as batch_op:
        batch_op.add_column(sa.Column('processed_filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=True))
        batch_op.add_column(sa.Column('filepath', sa.VARCHAR(length=512), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('filename', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('media_type', sa.VARCHAR(length=20), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('gallery_media_id')

    with op.batch_alter_table('activity_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('activity_media_id', sa.UUID(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('activity_configs_activity_media_id_fkey'), 'activity_media', ['activity_media_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_column('gallery_media_id')

    with op.batch_alter_table('activity_alerts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('activity_media_id', sa.UUID(), autoincrement=False, nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('activity_alerts_activity_media_id_fkey'), 'activity_media', ['activity_media_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_column('gallery_media_id')

    op.drop_table('gallery_media')
