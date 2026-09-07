"""Execute positive browser fixture generators against the real profile grammar.

Other services retain their own key contracts. Deliberately invalid profile
keys and legacy stored-ledger values must not be normalized by this sweep.
"""
import json
from pathlib import Path
import re
import subprocess

import pytest

from app.services.profile_service import (
    ProfileBoundaryError, validate_profile_idempotency_key,
)

ROOT = Path(__file__).resolve().parents[2]
BROWSER = ROOT / "frontend/scripts/nyay5-profile-browser.mjs"


def helper_source():
    source = BROWSER.read_text()
    matches = re.findall(
        r"function profileFixtureIdempotencyKey\(\) \{\n.*?\n\}",
        source, re.DOTALL,
    )
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("byte", [0, 85, 170, 255])
def test_actual_browser_positive_generator_reaches_profile_oracle(byte):
    # Execute the real helper with controlled entropy, not a reimplemented key.
    script = "const remembered=[]; const rememberPrivate=k=>remembered.push(k);"
    script += f"const randomBytes=n=>Buffer.alloc(n,{byte});"
    script += helper_source()
    script += "const key=profileFixtureIdempotencyKey(); console.log(JSON.stringify({key,remembered}));"
    result = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
    key = result["key"]
    assert validate_profile_idempotency_key(key) == key
    assert result["remembered"] == [key]
    assert key == "profile-" + f"{byte:02x}" * 24


@pytest.mark.parametrize("prefix", ["nyay5-profile-", "nyay2-profile-owner-", "nyay9-profile-"])
def test_legacy_positive_prefixes_remain_strictly_rejected(prefix):
    key = prefix + "a" * 48
    with pytest.raises(ProfileBoundaryError) as rejected:
        validate_profile_idempotency_key(key)
    assert rejected.value.code == "invalid_idempotency_key"
    assert rejected.value.field == "Idempotency-Key"
    assert key not in str(rejected.value)


def test_profile_call_sites_share_helper_and_registration_remains_separate():
    source = BROWSER.read_text()
    assert source.count("'Idempotency-Key': profileFixtureIdempotencyKey()") == 3
    assert "const idempotencyKey = `nyay5-browser-${nonce}`;" in source
    assert "`${API}/api/v1/auth/student/register`" in source
    assert "throw new Error('NYAY5_CROSS_SECTION_SETUP_FAILED')" in source


def test_shipped_profile_generator_remains_authoritative_and_unmodified():
    source = (ROOT / "frontend/src/features/student/lib/profileApi.ts").read_text()
    assert "randomUUID" in source and "getRandomValues" in source
    assert "profile-${" in source
    assert validate_profile_idempotency_key("profile-" + "a" * 48)


def test_positive_helper_uses_cryptographic_entropy_and_privacy_registration():
    source = helper_source()
    assert "randomBytes(24).toString('hex')" in source
    assert "rememberPrivate(key)" in source
    assert "Date.now" not in source and "Math.random" not in source
