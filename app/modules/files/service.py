"""File upload rules: size cap, extension allow-list, magic-byte check, sanitised
names. Downloads always send `attachment` + `nosniff`, so an uploaded file can never
be rendered by the browser as a page of ours (no stored XSS)."""

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import set_org_context
from app.core.errors import AppError, BusinessRuleViolation, Forbidden, NotFound
from app.modules.collab.service import entity_exists
from app.modules.files.models import FileAsset
from app.modules.files.storage import get_storage, new_key
from app.platform.audit import record_audit

ALLOWED: dict[str, tuple[str, ...]] = {
    "pdf": ("application/pdf",),
    "png": ("image/png",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "gif": ("image/gif",),
    "webp": ("image/webp",),
    "txt": ("text/plain",),
    "csv": ("text/csv", "text/plain", "application/vnd.ms-excel"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    "zip": ("application/zip", "application/x-zip-compressed"),
}
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "pptx": (b"PK\x03\x04",),
    "zip": (b"PK\x03\x04",),
}


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"
    title = "File is too large"


def sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    base = re.sub(r"\s+", " ", base)[:200]
    return base or "file"


def upload(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
) -> FileAsset:
    limit = get_settings().max_upload_bytes
    if len(data) > limit:
        raise PayloadTooLarge(f"Files may be at most {limit // (1024 * 1024)} MB")
    if not data:
        raise BusinessRuleViolation("The file is empty", code="empty_file")
    clean = sanitize_filename(filename)
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    if ext not in ALLOWED:
        raise BusinessRuleViolation(f"'.{ext}' files are not allowed", code="file_type_not_allowed")
    declared = content_type.split(";")[0].strip().lower()
    if declared not in ALLOWED[ext] and declared != "application/octet-stream":
        raise BusinessRuleViolation(
            "Content type does not match the file extension", code="content_type_mismatch"
        )
    magic = _MAGIC.get(ext)
    if magic and not data.startswith(magic):
        raise BusinessRuleViolation(
            "File contents do not match its extension", code="content_mismatch"
        )

    set_org_context(db, org_id)
    if not entity_exists(db, org_id, entity_type, entity_id):
        raise NotFound(f"{entity_type.capitalize()} not found")
    key = new_key(org_id)
    get_storage().put(key, data)
    asset = FileAsset(
        org_id=org_id,
        entity_type=entity_type,
        entity_id=entity_id,
        filename=clean,
        content_type=ALLOWED[ext][0],
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        uploaded_by=user_id,
    )
    db.add(asset)
    try:
        db.flush()
        record_audit(
            db,
            org_id=org_id,
            actor_user_id=user_id,
            action="file.uploaded",
            entity_type=entity_type,
            entity_id=entity_id,
            data={"file_id": str(asset.id), "name": clean},
        )
        db.commit()
    except Exception:
        db.rollback()
        get_storage().delete(key)  # never leave an orphaned blob behind a failed commit
        raise
    return asset


def get(db: Session, org_id: uuid.UUID, file_id: uuid.UUID) -> FileAsset:
    set_org_context(db, org_id)
    a = db.scalar(select(FileAsset).where(FileAsset.org_id == org_id, FileAsset.id == file_id))
    if a is None:
        raise NotFound("File not found")
    return a


def list_for(
    db: Session, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> list[FileAsset]:
    set_org_context(db, org_id)
    return list(
        db.scalars(
            select(FileAsset)
            .where(
                FileAsset.org_id == org_id,
                FileAsset.entity_type == entity_type,
                FileAsset.entity_id == entity_id,
            )
            .order_by(FileAsset.created_at.desc())
        )
    )


def delete(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, can_moderate: bool, file_id: uuid.UUID
) -> None:
    a = get(db, org_id, file_id)
    if a.uploaded_by != user_id and not can_moderate:
        raise Forbidden("You can only delete files you uploaded")
    key = a.storage_key
    db.delete(a)
    record_audit(
        db,
        org_id=org_id,
        actor_user_id=user_id,
        action="file.deleted",
        entity_type=a.entity_type,
        entity_id=a.entity_id,
        data={"file_id": str(a.id), "name": a.filename},
    )
    db.commit()
    get_storage().delete(key)  # after commit: a rolled-back delete must keep its blob
