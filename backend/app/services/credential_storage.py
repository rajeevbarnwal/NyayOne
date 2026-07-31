"""Evidence-storage and malware-scanning boundary for credential trust.

The deterministic scanner is a development/test adapter. Production can bind a
provider implementation through the same dependency without changing routes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.integrations.storage import FilesystemStorageAdapter, StorageAdapter

ALLOWED_MIME_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
}


class EvidenceScanUnavailable(RuntimeError):
    """The scanner failed transiently; evidence must remain quarantined."""


@dataclass(frozen=True)
class ScanResult:
    state: str
    result_code: str
    provider: str


class EvidenceScanner(abc.ABC):
    @abc.abstractmethod
    def scan(self, data: bytes, *, detected_mime: str) -> ScanResult: ...


class DeterministicEvidenceScanner(EvidenceScanner):
    """Predictable scanner seam used for local and automated verification."""

    provider = "deterministic"

    def scan(self, data: bytes, *, detected_mime: str) -> ScanResult:
        marker = data.upper()
        if b"SCAN_PROVIDER_FAILURE" in marker:
            raise EvidenceScanUnavailable("scanner_unavailable")
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in marker:
            return ScanResult("infected", "malware_detected", self.provider)
        return ScanResult("clean", "clean", self.provider)


def detect_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_evidence(
    *,
    filename: str | None,
    declared_mime: str | None,
    data: bytes,
) -> str:
    if not data:
        raise ValueError("empty_evidence")
    if len(data) > settings.credential_max_file_bytes:
        raise ValueError("evidence_too_large")
    safe_name = Path(filename or "").name
    if not safe_name or safe_name != (filename or "") or "\x00" in safe_name:
        raise ValueError("unsafe_filename")
    detected = detect_mime(data)
    if detected is None:
        raise ValueError("unsupported_evidence_type")
    declared = (declared_mime or "").lower().split(";", 1)[0].strip()
    if declared != detected:
        raise ValueError("mime_mismatch")
    if Path(safe_name).suffix.lower() not in ALLOWED_MIME_EXTENSIONS[detected]:
        raise ValueError("extension_mismatch")
    return detected


def get_credential_storage() -> StorageAdapter:
    return FilesystemStorageAdapter(settings.credential_storage_root)


def get_evidence_scanner() -> EvidenceScanner:
    # Fail closed for any unrecognised provider until a production adapter is
    # explicitly bound and tested.
    if settings.credential_scanner_provider == "deterministic":
        return DeterministicEvidenceScanner()
    raise EvidenceScanUnavailable("scanner_provider_not_configured")
