"""Opaque public organisation identifiers shared by listings and risk labels."""
from __future__ import annotations

import unicodedata
import uuid

from app.core.crypto import decrypt, keyed_hash

# Public organisation identifiers are route identifiers, not security tokens.
# Their namespace is deliberately fixed and versioned: rotating an encryption
# or lookup secret must never change an existing public URL or orphan a
# published label. Organisation names are already public catalogue data.
_PUBLIC_ORGANISATION_NAMESPACE_V1 = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://legalsaathi.in/namespaces/public-organisation/v1",
)


def normalise_organisation(value: str) -> str:
    # Case-fold first, then NFC-normalise: case folding can itself introduce
    # decomposed code points.  This keeps a public route identifier stable for
    # canonically equivalent catalogue names without collapsing visually
    # confusable (but semantically different) Unicode characters.
    return unicodedata.normalize("NFC", " ".join(value.casefold().split()))


def public_organisation_id(value: str) -> uuid.UUID:
    """Return a stable UUIDv5 route identifier for a canonical public name."""
    return uuid.uuid5(_PUBLIC_ORGANISATION_NAMESPACE_V1, normalise_organisation(value))


class OrganisationIdentityIntegrityError(ValueError):
    """Encrypted organisation copy does not match its keyed identity."""


def decrypt_bound_organisation(ciphertext: str, expected_hash: str) -> str:
    """Decrypt an organisation name and bind it to the canonical keyed hash.

    Encryption protects confidentiality; this explicit binding prevents a
    valid ciphertext copied from another row from changing the organisation
    shown to moderators or used by a publication decision.
    """
    try:
        value = decrypt(ciphertext)
    except Exception as error:
        raise OrganisationIdentityIntegrityError(
            "organisation identity decryption failed"
        ) from error
    if keyed_hash(normalise_organisation(value), lower=True) != expected_hash:
        raise OrganisationIdentityIntegrityError("organisation identity binding failed")
    return value


def representative_verification_hash(
    organisation_id: uuid.UUID,
    verification_method: str,
    delivery_ref: str,
) -> str:
    """Bind a verified representative reference to one organisation + method."""
    canonical_ref = unicodedata.normalize(
        "NFC", " ".join(delivery_ref.casefold().split())
    )
    return keyed_hash(f"{organisation_id}:{verification_method}:{canonical_ref}")
