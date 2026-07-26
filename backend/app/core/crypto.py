"""Registration field protection (SAATHI-366/448).

Approved model (Product decision 2026-07-26 §5): sensitive lookup values are
stored as a normalized keyed HMAC hash (for uniqueness/search — never reversible)
PLUS Fernet ciphertext for authorized display. Raw mobile/email/enrolment/DOB are
never stored in plaintext or written to logs/URLs/audit snapshots.

Key management (SAATHI-366 C2/C3):
- A versioned key ring. Every ciphertext is stamped ``<version>:<token>`` so the
  active key version is recorded on the row and rotation is possible.
- ``decrypt`` tries the active key, then each prior key, so ciphertext produced
  under a rotated-out key stays readable (active + prior rotation support).
- FAIL CLOSED: in ``production``/``staging`` the process refuses to run crypto
  when the registration secret is absent or still the known development default.
  Tests inject an explicit test key via ``override_keyring``, so they are
  unaffected.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# Known development defaults that must never be used in production/staging.
_DEV_DEFAULT_SECRETS = frozenset({
    "dev-registration-secret-change-me",
    "dev-registration-lookup-change-me",
    "",
    "changeme",
    "change-me",
})
_FAIL_CLOSED_ENVS = frozenset({"production", "prod", "staging", "stage"})


class CryptoConfigError(RuntimeError):
    """Raised when crypto is misconfigured in an environment that must fail closed."""


@dataclass(frozen=True)
class KeyRing:
    """Active key plus any prior keys, each identified by a version label."""

    active_version: str
    secrets: dict[str, bytes]  # version -> raw secret bytes
    lookup_secret: bytes | None = None

    def active_secret(self) -> bytes:
        return self.secrets[self.active_version]


# Optional test override; when set it takes precedence over settings.
_override: KeyRing | None = None


def _parse_prior_keys(raw: list[str]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for entry in raw or []:
        if ":" not in entry:
            continue
        version, secret = entry.split(":", 1)
        version, secret = version.strip(), secret.strip()
        if version and secret:
            out[version] = secret.encode("utf-8")
    return out


def _build_keyring_from_settings() -> KeyRing:
    active_secret = settings.registration_secret.get_secret_value()
    lookup_secret = settings.registration_lookup_secret.get_secret_value()
    active_version = settings.registration_key_version or "v1"
    env = (settings.app_env or "").lower()
    if env in _FAIL_CLOSED_ENVS and (
        active_secret in _DEV_DEFAULT_SECRETS
        or lookup_secret in _DEV_DEFAULT_SECRETS
    ):
        raise CryptoConfigError(
            "registration encryption/lookup secret is unset or a development default in a "
            f"fail-closed environment ({settings.app_env!r}). Set a strong secret."
        )
    secrets = {active_version: active_secret.encode("utf-8")}
    # Prior keys never override the active version.
    for version, secret in _parse_prior_keys(settings.registration_prior_keys).items():
        secrets.setdefault(version, secret)
    return KeyRing(
        active_version=active_version,
        secrets=secrets,
        lookup_secret=lookup_secret.encode("utf-8"),
    )


def get_keyring() -> KeyRing:
    return _override if _override is not None else _build_keyring_from_settings()


def override_keyring(ring: KeyRing | None) -> None:
    """Test hook: pin an explicit key ring (or clear with None)."""
    global _override
    _override = ring


def assert_crypto_ready() -> None:
    """Startup guard. Raises CryptoConfigError if crypto would be insecure.

    Safe to call unconditionally; a no-op in development with the default key
    unless the environment is production/staging.
    """
    get_keyring()


def _fernet_for(secret: bytes) -> Fernet:
    # Derive a stable 32-byte urlsafe key from the configured secret.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def _hash_key() -> bytes:
    # Lookup hashes must remain stable while encryption keys rotate.
    ring = get_keyring()
    return ring.lookup_secret or ring.active_secret()


def normalize(value: str, *, lower: bool = False) -> str:
    v = (value or "").strip()
    return v.lower() if lower else v


def keyed_hash(value: str, *, lower: bool = False) -> str:
    """Deterministic keyed hash for uniqueness/lookup. Not reversible."""
    norm = normalize(value, lower=lower).encode("utf-8")
    return hmac.new(_hash_key(), norm, hashlib.sha256).hexdigest()


def encrypt(value: str) -> str:
    """Return version-stamped ciphertext ``<active_version>:<fernet_token>``."""
    ring = get_keyring()
    token = _fernet_for(ring.active_secret()).encrypt((value or "").encode("utf-8")).decode("ascii")
    return f"{ring.active_version}:{token}"


def key_version(stamped: str) -> str:
    """Extract the key version recorded on a ciphertext (``v1`` if unstamped)."""
    return stamped.split(":", 1)[0] if ":" in stamped else "v1"


def decrypt(stamped: str) -> str:
    """Decrypt a (possibly version-stamped) ciphertext, honouring key rotation."""
    ring = get_keyring()
    if ":" in stamped:
        version, token = stamped.split(":", 1)
    else:
        # Legacy/unstamped ciphertext predates versioning; try the active key.
        version, token = ring.active_version, stamped
    raw = token.encode("ascii")
    # Try the recorded version first, then every other key (rotation support).
    candidate_versions = [version, *[v for v in ring.secrets if v != version]]
    last_err: Exception | None = None
    for v in candidate_versions:
        secret = ring.secrets.get(v)
        if secret is None:
            continue
        try:
            return _fernet_for(secret).decrypt(raw).decode("utf-8")
        except InvalidToken as exc:  # pragma: no cover - exercised via rotation test
            last_err = exc
    raise InvalidToken(str(last_err) if last_err else "no key could decrypt token")


def active_key_version() -> str:
    return get_keyring().active_version


def otp_verifier(code: str, *, salt: str) -> str:
    """Store only a keyed verifier for an OTP — never the raw code."""
    return hmac.new(_hash_key(), f"{salt}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()
