"""extend_username_to_50

Revision ID: 09bb7eb6ec2a
Revises: 002_recency_decay
Create Date: 2026-07-02 18:54:40.934803
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision: str = "09bb7eb6ec2a"
down_revision: Union[str, None] = "002_recency_decay"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "username",
        existing_type=sa.VARCHAR(length=15),
        type_=sa.String(length=50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "username",
        existing_type=sa.String(length=50),
        type_=sa.VARCHAR(length=15),
        existing_nullable=False,
    )
