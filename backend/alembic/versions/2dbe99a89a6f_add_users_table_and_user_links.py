"""add_users_table_and_user_links

Revision ID: 2dbe99a89a6f
Revises: fbed807cad50
Create Date: 2026-02-01 12:56:08.431766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2dbe99a89a6f'
down_revision: Union[str, Sequence[str], None] = 'fbed807cad50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('google_id', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('profile_picture', sa.Text(), nullable=True),
        sa.Column('google_access_token', sa.Text(), nullable=True),
        sa.Column('google_refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('drive_folder_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_login', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('google_id')
    )
    op.create_index('idx_users_google_id', 'users', ['google_id'], unique=False)
    op.create_index('idx_users_email', 'users', ['email'], unique=False)

    # Add user_id to notes
    op.add_column('notes', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_notes_user_id', 'notes', 'users', ['user_id'], ['id'])
    op.create_index('idx_notes_user_id', 'notes', ['user_id'], unique=False)
    
    # Add drive related columns to notes
    op.add_column('notes', sa.Column('drive_file_id', sa.String(length=255), nullable=True))
    op.add_column('notes', sa.Column('drive_web_link', sa.Text(), nullable=True))

    # Add user_id to study_sessions
    op.add_column('study_sessions', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_study_sessions_user_id', 'study_sessions', 'users', ['user_id'], ['id'])
    op.create_index('idx_study_sessions_user_id', 'study_sessions', ['user_id'], unique=False)

    # Add user_id to user_uploads
    op.add_column('user_uploads', sa.Column('user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_user_uploads_user_id', 'user_uploads', 'users', ['user_id'], ['id'])
    op.create_index('idx_user_uploads_user_id', 'user_uploads', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_user_uploads_user_id', 'user_uploads', type_='foreignkey')
    op.drop_index('idx_user_uploads_user_id', table_name='user_uploads')
    op.drop_column('user_uploads', 'user_id')

    op.drop_constraint('fk_study_sessions_user_id', 'study_sessions', type_='foreignkey')
    op.drop_index('idx_study_sessions_user_id', table_name='study_sessions')
    op.drop_column('study_sessions', 'user_id')

    op.drop_index('idx_notes_user_id', table_name='notes')
    op.drop_constraint('fk_notes_user_id', 'notes', type_='foreignkey')
    op.drop_column('notes', 'drive_web_link')
    op.drop_column('notes', 'drive_file_id')
    op.drop_column('notes', 'user_id')

    op.drop_index('idx_users_email', table_name='users')
    op.drop_index('idx_users_google_id', table_name='users')
    op.drop_table('users')
