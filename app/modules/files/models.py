import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, created_at_col, uuid_pk


class FileAsset(Base):
    """Metadata for an uploaded file attached to an entity (project, task, client,
    deal, proposal or invoice). The bytes live in the storage backend."""

    __tablename__ = "file_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "uploaded_by"],
            ["users.org_id", "users.id"],
            name="fk_file_assets_org_id_users",
            ondelete="RESTRICT",
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_file_assets_org_id_entity", "org_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()
