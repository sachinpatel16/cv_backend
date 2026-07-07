import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context, script
from alembic.runtime.migration import MigrationContext

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Ensure project root is on sys.path so 'app' package is importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import your SQLAlchemy Base and models
# This must come AFTER the path setup
from database.base import Base

from modules.organizations.model import Organization
from modules.users.model import User
from modules.permissions.model import UserPermission
from modules.peoplefind.model import MediaSource, FaceEmbedding, FaceSearchSession, FaceSearchResult
from modules.employees.model import Employee, EmployeeEmbedding
from modules.gallery.model import GalleryMedia

from modules.peopleanalytics.model import (
    UploadedVideo,
    EmployeeAttendanceLog,
    PeopleAnalyticsSession,
    PersonIdentity,
    PersonEmbedding,
    PersonOccurrence,
    LineCrossingLog,
    VisitorAttendanceLog
)
from modules.peoplecount.model import PeopleCountMedia, PeopleCountResult
from modules.objectcount.model import ObjectCountMedia, ObjectCountResult
from modules.activity.model import ActivityConfig, ActivityAlert
from modules.peoplecount.model import PeopleCountMedia, PeopleCountResult
from modules.objectcount.model import ObjectCountMedia, ObjectCountResult
from modules.activity.model import ActivityConfig, ActivityAlert

from modules.smokingdetect.model import SmokingSession, SmokingEvent


# Set target metadata for 'autogenerate'
target_metadata = Base.metadata

# Get database URL from environment variable or configs
from configs.base import settings
DATABASE_URL = os.getenv("DATABASE_URL") or settings.DATABASE_URL

# Translate asyncpg scheme to sync scheme for Alembic's sync engine
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

config.set_main_option("sqlalchemy.url", DATABASE_URL)
print(
    f"Using database URL: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'configured'}"
)  # Print without credentials


def process_revision_directives(context, revision, directives):
    """Hook to set sequential revision IDs (0001, 0002, etc.)"""
    if config.get_main_option("revision_environment") == "true":
        # Get the script directory and existing revisions
        script_dir = script.ScriptDirectory.from_config(config)
        revs = list(script_dir.walk_revisions())
        
        # Calculate next number
        next_num = len(revs) + 1
        new_rev_id = f"{next_num:04d}"
        
        for directive in directives:
            directive.rev_id = new_rev_id


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,  # For SQLite compatibility
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Connect to the database
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=True,  # For SQLite compatibility
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
