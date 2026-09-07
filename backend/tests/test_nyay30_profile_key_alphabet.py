"""NYAY-30 v1: exact alphabet shared by UUID and profile-hex generators."""
from pathlib import Path
import uuid

import pytest

from app.services.profile_service import (
    ProfileBoundaryError, validate_profile_idempotency_key,
)


@pytest.mark.parametrize("value", [
    str(uuid.UUID("c4c2da3e-3e33-4887-9db2-331e8744e125")),
    "profile-39c426f86e0bd2a194b7e63acd195804",
    "abcdef0123456789",
    "a" * 200,
])
def test_shipped_generators_and_existing_length_bounds_remain_valid(value):
    assert validate_profile_idempotency_key(value) == value


@pytest.mark.parametrize("character", [".", "_", "~", "z", "g", "A"])
def test_previously_tolerated_outside_alphabet_is_rejected(character):
    value = "profile-39c426f86e0bd2a194b7e63acd195804" + character
    with pytest.raises(ProfileBoundaryError) as rejected:
        validate_profile_idempotency_key(value)
    assert rejected.value.code == "invalid_idempotency_key"
    assert rejected.value.field == "Idempotency-Key"
    assert value not in str(rejected.value)


@pytest.mark.parametrize("value", [None, "", " ", "short", "a" * 15,
    "a" * 201, "profile-private@example.invalid", "a" * 16 + "\n",
    "profile-39c426f8,profile-39c426f8"])
def test_missing_short_duplicate_whitespace_pii_and_length_remain_rejected(value):
    with pytest.raises(ProfileBoundaryError):
        validate_profile_idempotency_key(value)


def test_grammar_is_versioned_and_binds_the_shipped_generator():
    from app.services import profile_service
    assert getattr(profile_service, "PROFILE_IDEMPOTENCY_GRAMMAR_VERSION", None) == "profile-key-alphabet.v1"
    assert getattr(profile_service, "PROFILE_IDEMPOTENCY_ALPHABET", None) == "-0123456789abcdefilopr"
    source = (Path(__file__).resolve().parents[2] /
              "frontend/src/features/student/lib/profileApi.ts").read_text()
    assert "randomUUID" in source and "getRandomValues" in source
    assert "profile-${" in source and ".toString(16)" in source
