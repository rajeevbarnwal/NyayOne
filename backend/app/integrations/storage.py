"""File-storage abstraction (SAATHI-339).

An S3-compatible interface with a local filesystem adapter for dev/tests. No
production provider and NO MinIO (per stack decision); SeaweedFS/S3 is wired
later behind this same interface. Includes a signed-URL interface, checksum
computation, and a retention-policy hook. Object bytes live in the store; row
metadata is described by `FileMetadata` (aligned to LegalSaathi_Data_Model_v0.1
`files`).
"""
from __future__ import annotations

import abc
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileMetadata:
    """Metadata contract mirroring the `files` table (bytes stored separately)."""

    storage_key: str
    kind: str = "generic"  # file_kind enum in DB
    mime_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    visibility: str = "private"
    retention_policy: str | None = None
    owner_user_id: uuid.UUID | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StorageAdapter(abc.ABC):
    """S3-compatible surface. Implementations must not leak provider specifics."""

    @abc.abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> FileMetadata: ...

    @abc.abstractmethod
    def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    def signed_url(self, key: str, *, expires_in: int = 900, method: str = "GET") -> str: ...


class FilesystemStorageAdapter(StorageAdapter):
    """Local dev/test adapter. Signed URLs are opaque local tokens (not real S3
    presigned URLs) — sufficient for dev; the S3 adapter overrides this later."""

    def __init__(self, root: str | os.PathLike[str], public_base_url: str = "http://localhost:1035"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        # Prevent path traversal outside the root.
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("Invalid storage key")
        return p

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> FileMetadata:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return FileMetadata(
            storage_key=key,
            mime_type=content_type,
            size_bytes=len(data),
            checksum_sha256=compute_checksum(data),
        )

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def signed_url(self, key: str, *, expires_in: int = 900, method: str = "GET") -> str:
        expiry = int(time.time()) + expires_in
        # Opaque dev token; real adapters return provider presigned URLs.
        token = hashlib.sha256(f"{key}:{expiry}:{method}".encode()).hexdigest()[:16]
        return f"{self.public_base_url}/{key}?method={method}&expires={expiry}&sig={token}"


class RetentionPolicy:
    """Retention hook — resolves a data-class label to a retention window.
    Concrete windows come from TDD 13.2.1; this is the extension point."""

    _DEFAULT_DAYS = {
        "profile_evidence": 730,
        "application_doc": 1095,
        "clinical_evidence": 2555,
        "report_evidence": 730,
        "generic": 365,
    }

    @classmethod
    def days_for(cls, file_kind: str) -> int:
        return cls._DEFAULT_DAYS.get(file_kind, cls._DEFAULT_DAYS["generic"])


def get_storage_adapter(root: str | os.PathLike[str] | None = None) -> StorageAdapter:
    """Factory. Dev/test → filesystem. Production S3/SeaweedFS adapter added later
    behind this same call, selected by settings."""
    return FilesystemStorageAdapter(root or "/tmp/legalsaathi_storage")
