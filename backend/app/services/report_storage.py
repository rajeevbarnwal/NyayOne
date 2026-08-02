"""Private-report evidence validation, scanning and storage seams.

No filename or file content is persisted in PostgreSQL.  Validation inspects the
actual signature, declared MIME and extension before a random opaque object key
is created.  Scanner outages fail closed and leave evidence quarantined.
"""
from __future__ import annotations

import socket
import struct
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.integrations.storage import FilesystemStorageAdapter, StorageAdapter

ALLOWED_MIME_EXTENSIONS: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({".pdf"}),
    "image/png": frozenset({".png"}),
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
}


class ReportEvidenceScanUnavailable(RuntimeError):
    pass


class ReportEvidenceInfected(RuntimeError):
    pass


class ReportEvidenceScanner(ABC):
    @abstractmethod
    def scan(self, data: bytes) -> str: ...


class DeterministicReportEvidenceScanner(ReportEvidenceScanner):
    """Deterministic local adapter; production must bind an approved scanner."""

    def scan(self, data: bytes) -> str:
        upper = data.upper()
        if b"SCANNER_UNAVAILABLE" in upper:
            raise ReportEvidenceScanUnavailable("scanner_unavailable")
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in upper:
            raise ReportEvidenceInfected("malware_detected")
        return "clean"


class ClamAVReportEvidenceScanner(ReportEvidenceScanner):
    """Production clamd INSTREAM adapter.

    Data is streamed over the private scanner connection and never written to
    process logs. Any protocol, network or timeout error fails closed as a
    retryable scanner outage; only an explicit ``OK`` releases quarantine.
    """

    def __init__(self, host: str, port: int, timeout_seconds: float = 10.0):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def scan(self, data: bytes) -> str:
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(b"zINSTREAM\0")
                for offset in range(0, len(data), 64 * 1024):
                    chunk = data[offset:offset + 64 * 1024]
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(struct.pack("!I", 0))
                response = bytearray()
                while len(response) < 4096:
                    part = connection.recv(4096 - len(response))
                    if not part:
                        break
                    response.extend(part)
                    if b"\0" in part or b"\n" in part:
                        break
        except (OSError, TimeoutError) as exc:
            raise ReportEvidenceScanUnavailable("scanner_unavailable") from exc
        verdict = bytes(response).rstrip(b"\0\r\n")
        if verdict.endswith(b" OK"):
            return "clean"
        if verdict.endswith(b" FOUND"):
            raise ReportEvidenceInfected("malware_detected")
        raise ReportEvidenceScanUnavailable("scanner_invalid_response")


def detect_report_evidence_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def validate_report_evidence(
    *, filename: str | None, declared_mime: str | None, data: bytes
) -> str:
    if not data:
        raise ValueError("empty_evidence")
    if len(data) > settings.internship_report_max_file_bytes:
        raise ValueError("evidence_too_large")
    safe_name = Path(filename or "").name
    if not safe_name or safe_name != (filename or "") or "\x00" in safe_name:
        raise ValueError("unsafe_filename")
    detected = detect_report_evidence_mime(data)
    if detected is None:
        raise ValueError("unsupported_evidence_type")
    declared = (declared_mime or "").lower().split(";", 1)[0].strip()
    if declared != detected:
        raise ValueError("mime_mismatch")
    if Path(safe_name).suffix.lower() not in ALLOWED_MIME_EXTENSIONS[detected]:
        raise ValueError("extension_mismatch")
    return detected


def get_report_storage() -> StorageAdapter:
    return FilesystemStorageAdapter(settings.internship_report_storage_root)


def get_report_evidence_scanner() -> ReportEvidenceScanner:
    if settings.internship_report_scanner_provider == "deterministic":
        return DeterministicReportEvidenceScanner()
    if settings.internship_report_scanner_provider == "clamav":
        return ClamAVReportEvidenceScanner(
            settings.internship_report_clamav_host,
            settings.internship_report_clamav_port,
            settings.internship_report_clamav_timeout_seconds,
        )
    raise ReportEvidenceScanUnavailable("scanner_provider_not_configured")
