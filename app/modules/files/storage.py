"""Blob storage behind a tiny interface so S3/GCS can replace the local disk later.

Keys are server-generated (`<org_id>/<uuid>`), never derived from user input, so a
crafted filename can never escape the storage root."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("storage key escapes the storage root")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)  # atomic: readers never see a partial file

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def new_key(org_id: uuid.UUID) -> str:
    return f"{org_id}/{uuid.uuid4().hex}"


def get_storage() -> Storage:
    return LocalStorage(get_settings().storage_dir)


def iter_file(handle: BinaryIO, chunk: int = 64 * 1024) -> Iterator[bytes]:
    with handle:
        while block := handle.read(chunk):
            yield block
