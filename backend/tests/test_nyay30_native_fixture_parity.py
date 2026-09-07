"""Native positive fixtures must reach the intended oracle, not key rejection."""
import ast
import hashlib
from pathlib import Path
import re

import pytest

from app.services.profile_service import (
    ProfileBoundaryError, validate_profile_idempotency_key,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def source(name):
    return (SCRIPTS / name).read_text()


def nyay2_headers():
    # Execute the actual pure fixture function without loading DB/runtime setup.
    tree = ast.parse(source("nyay2_postgres_authorization_gate.py"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "_profile_mutation_headers")
    namespace = {"re": re, "hashlib": hashlib,
                 "_trusted_mutation_headers": lambda: {"Origin": "https://ci.nyayone.example"}}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "native-fixture", "exec"), namespace)
    return namespace["_profile_mutation_headers"]


@pytest.mark.parametrize("label", ["owner-a", "owner-b", "mutant-owner", "origin-0", "mutant-origin"])
def test_nyay2_positive_fixture_reaches_authorization_boundary(label):
    key = nyay2_headers()(label)["Idempotency-Key"]
    assert validate_profile_idempotency_key(key) == key


@pytest.mark.parametrize("label", ["owner-a", "owner-b", "mutant-owner", "origin-0", "mutant-origin"])
def test_nyay2_legacy_positive_key_still_rejected_by_nyay30(label):
    legacy = f"nyay2-profile-{label}-0001"
    with pytest.raises(ProfileBoundaryError) as rejected:
        validate_profile_idempotency_key(legacy)
    assert rejected.value.code == "invalid_idempotency_key"
    assert rejected.value.field == "Idempotency-Key"
    assert legacy not in str(rejected.value)


def test_nyay2_fixture_preserves_origin_multiplicity_and_replay_identity():
    headers = nyay2_headers()
    repeated = [("Origin", "https://ci.nyayone.example"), ("Origin", "https://other.example")]
    result = headers("owner-a", headers=repeated)
    assert result[:-1] == repeated
    assert repeated == [("Origin", "https://ci.nyayone.example"), ("Origin", "https://other.example")]
    assert result[-1] == ("Idempotency-Key", headers("owner-a")["Idempotency-Key"])
    assert headers("owner-a") == headers("owner-a")
    assert headers("owner-a")["Idempotency-Key"] != headers("owner-b")["Idempotency-Key"]


def test_nyay5_injected_native_key_uses_shipped_generator():
    tree = ast.parse(source("nyay5_postgres_profile_gate.py"))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_profile_mutation_headers")
    key = call.args[2]
    assert isinstance(key, ast.JoinedStr)
    rendered = "".join(n.value if isinstance(n, ast.Constant) else "a" * 32
                       for n in key.values)
    assert validate_profile_idempotency_key(rendered) == rendered


def test_nyay9_native_positive_key_literals_are_valid():
    tree = ast.parse(source("nyay9_postgres_profile_gate.py"))
    # These closed positive examples must not turn unrelated ownership, replay,
    # concurrency or DOB assertions into invalid-key failures.
    keys = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys.extend(v.value for k, v in zip(n.keys, n.values)
                        if isinstance(k, ast.Constant) and k.value == "Idempotency-Key"
                        and isinstance(v, ast.Constant))
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                and t.id in ("shared_key", "replay_key") for t in n.targets):
            keys.append(n.value.value)
        if isinstance(n, ast.Tuple) and len(n.elts) == 2 and all(
                isinstance(e, ast.Constant) for e in n.elts):
            if n.elts[1].value in ("FirstCity", "SecondCity"):
                keys.append(n.elts[0].value)
    assert len(keys) == 7
    for value in keys:
        assert validate_profile_idempotency_key(value) == value
    assert len(set(keys)) == 7


def test_shared_and_distinct_concurrency_relationships_preserved():
    text = source("nyay9_postgres_profile_gate.py")
    assert len(re.findall(r'"Idempotency-Key": shared_key', text)) == 2
    assert len(re.findall(r'"Idempotency-Key": replay_key', text)) == 2
    assert '"Idempotency-Key": key' in text
    assert '"FirstCity"' in text and '"SecondCity"' in text
