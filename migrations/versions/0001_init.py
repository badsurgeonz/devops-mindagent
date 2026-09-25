"""init schema

Revision ID: 0001
Revises:
Create Date: 2026-09-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.base import Base
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db.base import Base

    for table in reversed(Base.metadata.sorted_tables):
        op.drop_table(table.name)