import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.permissions import Perm, Role, has_permission
from app.modules.collab.access import authorize_entity
from app.modules.files import service
from app.modules.files.service import PayloadTooLarge
from app.modules.files.storage import get_storage, iter_file
from app.modules.identity.deps import require
from app.modules.identity.models import User

router = APIRouter(prefix="/files", tags=["files"])
Db = Annotated[Session, Depends(get_db)]
Writer = Annotated[User, Depends(require(Perm.FILE_WRITE))]
Reader = Annotated[User, Depends(require(Perm.FILE_READ))]


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: uuid.UUID


@router.post("", response_model=FileOut, status_code=201)
async def upload(
    user: Writer,
    db: Db,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> FileOut:
    authorize_entity(db, user, entity_type, entity_id)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)  # never buffer more than the cap + 1 byte
    if len(data) > limit:
        raise PayloadTooLarge(f"Files may be at most {limit // (1024 * 1024)} MB")
    asset = service.upload(
        db,
        org_id=user.org_id,
        user_id=user.id,
        entity_type=entity_type,
        entity_id=entity_id,
        filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    return FileOut.model_validate(asset)


@router.get("", response_model=list[FileOut])
def list_files(entity_type: str, entity_id: uuid.UUID, user: Reader, db: Db) -> list[FileOut]:
    authorize_entity(db, user, entity_type, entity_id)
    return [
        FileOut.model_validate(a) for a in service.list_for(db, user.org_id, entity_type, entity_id)
    ]


@router.get("/{file_id}/download")
def download(file_id: uuid.UUID, user: Reader, db: Db) -> StreamingResponse:
    a = service.get(db, user.org_id, file_id)
    authorize_entity(db, user, a.entity_type, a.entity_id)
    safe = a.filename.replace('"', "")
    return StreamingResponse(
        iter_file(get_storage().open(a.storage_key)),
        media_type=a.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(a.size_bytes),
        },
    )


@router.delete("/{file_id}", status_code=204)
def delete(file_id: uuid.UUID, user: Writer, db: Db) -> None:
    service.delete(
        db,
        org_id=user.org_id,
        user_id=user.id,
        file_id=file_id,
        can_moderate=has_permission(Role(user.role), Perm.USER_MANAGE),
    )
