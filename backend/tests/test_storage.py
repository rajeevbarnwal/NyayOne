"""Tests for the file-storage abstraction (SAATHI-339)."""
from __future__ import annotations

import uuid

from app.integrations.storage import (
    FileMetadata,
    FilesystemStorageAdapter,
    RetentionPolicy,
    compute_checksum,
    get_storage_adapter,
)


def test_filesystem_put_get_delete_roundtrip(tmp_path) -> None:
    store = FilesystemStorageAdapter(tmp_path)
    data = b"hello legalsaathi"
    meta = store.put("evidence/doc1.txt", data, content_type="text/plain")
    assert isinstance(meta, FileMetadata)
    assert meta.size_bytes == len(data)
    assert meta.checksum_sha256 == compute_checksum(data)
    assert store.exists("evidence/doc1.txt")
    assert store.get("evidence/doc1.txt") == data
    store.delete("evidence/doc1.txt")
    assert store.exists("evidence/doc1.txt") is False


def test_signed_url_has_expiry_and_signature(tmp_path) -> None:
    store = FilesystemStorageAdapter(tmp_path, public_base_url="http://localhost:1035")
    url = store.signed_url("evidence/doc1.txt", expires_in=600, method="GET")
    assert url.startswith("http://localhost:1035/evidence/doc1.txt")
    assert "expires=" in url and "sig=" in url and "method=GET" in url


def test_path_traversal_blocked(tmp_path) -> None:
    store = FilesystemStorageAdapter(tmp_path)
    try:
        store.put("../escape.txt", b"x")
        assert False, "expected traversal to be blocked"
    except ValueError:
        pass


def test_file_metadata_contract_fields() -> None:
    m = FileMetadata(storage_key="k", kind="clinical_evidence", owner_user_id=uuid.uuid4())
    for f in ("id", "storage_key", "kind", "mime_type", "size_bytes", "checksum_sha256", "visibility", "retention_policy", "owner_user_id"):
        assert hasattr(m, f)
    assert m.visibility == "private"


def test_retention_policy_hook() -> None:
    assert RetentionPolicy.days_for("clinical_evidence") == 2555
    assert RetentionPolicy.days_for("unknown_kind") == RetentionPolicy.days_for("generic")


def test_factory_returns_adapter(tmp_path) -> None:
    assert isinstance(get_storage_adapter(tmp_path), FilesystemStorageAdapter)
