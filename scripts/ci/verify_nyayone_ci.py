#!/usr/bin/env python3
"""Fail-closed static policy checks for NyayOne GitHub Actions workflows."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by the CI bootstrap
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DB_GATE = ROOT / "backend" / "scripts" / "db_gate.sh"
NYAY4_BROWSER_GATE = ROOT / "frontend" / "scripts" / "nyay4-otp-browser-negative.mjs"
NYAY4_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay4-otp-runner-contract.mjs"
)
NYAY4_BROWSER_CONTRACT_TEST = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay4-otp-runner-contract.test.mjs"
)
NYAY22_BROWSER_GATE = (
    ROOT / "frontend" / "scripts" / "nyay22-mentor-ceremony-browser.mjs"
)
NYAY22_BROWSER_CONTRACT = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay22-mentor-ceremony-browser-contract.mjs"
)
NYAY22_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay22-mentor-ceremony-browser-contract.test.mjs"
)
NYAY22_BROWSER_HARNESS_ENTRY = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay22-browser-harness-entry.ts"
)
NYAY22_BROWSER_FIXTURE = (
    ROOT / "frontend" / "scripts" / "fixtures" / "nyay22-browser-harness.html"
)
NYAY22_BROWSER_SEED = ROOT / "backend" / "scripts" / "seed_nyay22_browser_fixture.py"
NYAY22_BROWSER_SEED_TEST = (
    ROOT / "backend" / "tests" / "test_nyay22_browser_fixture_seed.py"
)
NYAY22_POSTGRES_GATE = (
    ROOT / "backend" / "scripts" / "nyay22_postgres_mentor_gate.py"
)
NYAY22_POSTGRES_CONTRACT = (
    ROOT / "scripts" / "ci" / "nyay22-mentor-postgres-contract.json"
)
NYAY22_SCHEMA_MIGRATION = (
    ROOT
    / "backend"
    / "app"
    / "db"
    / "migrations"
    / "versions"
    / "0023_nyay22_mentor_ceremony.py"
)
NYAY22_MENTOR_AUTH_MODEL = ROOT / "backend" / "app" / "models" / "mentor_auth.py"
NYAY22_MIGRATION_DISPATCH_TEST = (
    ROOT / "backend" / "tests" / "test_nyay22_migration_dispatch_contract.py"
)
NYAY22_NYAY19_ERASURE_TEST = (
    ROOT / "backend" / "tests" / "test_nyay22_nyay19_erasure_integration.py"
)
NYAY22_REQUIRED_WORKFLOW = WORKFLOWS / "wave3-credential-trust-gate.yml"
NYAY19_BROWSER_GATE = (
    ROOT / "frontend" / "scripts" / "nyay19-auth-lifecycle-browser.mjs"
)
NYAY19_BROWSER_CONTRACT = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay19-auth-lifecycle-runner-contract.mjs"
)
NYAY19_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay19-auth-lifecycle-runner-contract.test.mjs"
)
NYAY5_BROWSER_ORCHESTRATOR = ROOT / "scripts" / "nyay5_profile_browser_gate.sh"
NYAY5_BROWSER_GATE = ROOT / "frontend" / "scripts" / "nyay5-profile-browser.mjs"
NYAY5_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay5-profile-browser-contract.mjs"
)
NYAY5_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay5-profile-browser-contract.test.mjs"
)
NYAY5_BROWSER_CONTROL = ROOT / "backend" / "scripts" / "nyay5_browser_gate_control.py"
NYAY5_POSTGRES_GATE = ROOT / "backend" / "scripts" / "nyay5_postgres_profile_gate.py"
NYAY5_ACCEPTANCE_AGGREGATE = (
    ROOT / "frontend" / "scripts" / "nyay5-acceptance-aggregate.mjs"
)
NYAY5_ACCEPTANCE_AGGREGATE_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay5-acceptance-aggregate.test.mjs"
)
NYAY5_ACCEPTANCE_ATTESTATION_PRODUCER = (
    ROOT / "scripts" / "ci" / "nyay5_acceptance_attestations.py"
)
NYAY5_ACCEPTANCE_ATTESTATION_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay5_acceptance_attestations.py"
)
NYAY18_NAMESPACE_GATE = (
    ROOT / "scripts" / "ci" / "check_nyay18_frontend_namespaces.py"
)
NYAY18_NAMESPACE_GATE_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay18_namespace_policy.py"
)
NYAY18_NAMESPACE_CONTRACT = (
    ROOT / "scripts" / "ci" / "nyay18_namespace_contract.json"
)
NYAY18_NAMESPACE_BOUNDARY_DOCUMENT = (
    ROOT / "docs" / "architecture" / "nyay18-frontend-browser-mobile-namespace-boundary.md"
)
NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST = (
    ROOT / "scripts" / "ci" / "test_nyay18_namespace_boundary_doc.py"
)
NYAY18_BROWSER_ORCHESTRATOR = ROOT / "scripts" / "nyay18_browser_namespace_gate.sh"
NYAY18_BROWSER_GATE = (
    ROOT / "frontend" / "scripts" / "nyay18-browser-namespace.mjs"
)
NYAY18_BROWSER_PREVIEW_SERVER = (
    ROOT / "frontend" / "scripts" / "nyay18-preview-server.mjs"
)
NYAY18_BROWSER_CONTRACT = (
    ROOT / "frontend" / "scripts" / "lib" / "nyay18-browser-contract.mjs"
)
NYAY18_BROWSER_CONTRACT_TEST = (
    ROOT
    / "frontend"
    / "scripts"
    / "lib"
    / "nyay18-browser-contract.test.mjs"
)
FRONTEND_PACKAGE = ROOT / "frontend" / "package.json"
NYAY14_EVIDENCE_FILES: dict[str, Path] = {
    "gate": ROOT / "scripts" / "ci" / "nyay14_evidence_gate.py",
    "tests": ROOT / "scripts" / "ci" / "test_nyay14_evidence_gate.py",
    "security_tests": (
        ROOT / "scripts" / "ci" / "test_nyay14_evidence_gate_security.py"
    ),
    "contact_sheet_tests": (
        ROOT / "scripts" / "ci" / "test_nyay27_contact_sheet_gate.py"
    ),
    "contract": ROOT / "scripts" / "ci" / "nyay14_evidence_contract.json",
    "contact_sheet_contract": (
        ROOT / "scripts" / "ci" / "nyay27_contact_sheet_contract.json"
    ),
    "privacy_scanner": ROOT / "scripts" / "ci" / "scan_evidence.py",
    "seeded_fixture": (
        ROOT / "scripts" / "ci" / "fixtures" / "nyay14" / "seeded_zero_assertions.json"
    ),
    "readme": ROOT / "docs" / "operations" / "nyay14-exact-head-evidence" / "README.md",
    "provenance_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "PROVENANCE.json"
    ),
    "raw_log_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "RAW_LOG_INVENTORY.json"
    ),
    "visual_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "VISUAL_COMPARISON_MATRIX.json"
    ),
    "contact_sheet_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "COMBINED_CONTACT_SHEET.json"
    ),
    "quality_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "QUALITY_RESULTS.json"
    ),
    "comment_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "PR_COMMENT.md"
    ),
    "merge_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "GUARDED_MERGE.md"
    ),
    "protected_checkout_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "PROTECTED_CHECKOUT.json"
    ),
    "readbacks_template": (
        ROOT
        / "docs"
        / "operations"
        / "nyay14-exact-head-evidence"
        / "templates"
        / "READBACKS.json"
    ),
}
EXPECTED_NYAY14_EVIDENCE_SHA256: dict[str, str] = {
    "gate": "50975750724f0e80e6fb5f9e642df14d004f0ce750c2b7f1989169409097b218",
    "tests": "a0a8dd8a05fcaac010c4c627ccdc166c50dc8c002cf48f09fb90602dd96db208",
    "security_tests": "ff5453339d848797b75c2a575807ca56d6c06b7b3c0bcc6e88507324ff2b9ca5",
    "contact_sheet_tests": "36c70a1ee17e037f52ab3bcf9382ac5b6252fad76cefdebdb5cf009977a03b9c",
    "contract": "2790051d8364ea3bbfde5d4dd101d7926b30873dafc0eb68dfa6d89ee487c9a9",
    "contact_sheet_contract": "393bb8cf153567b1b0fa50a899de5c34ff6343ee229b708dba91f5dd010b3773",
    "privacy_scanner": "c06a9a819b9aecd77e2742a17d690e6a0657c7fe6435dc315d78a887ae34cd96",
    "seeded_fixture": "2e2bff9a8369e244ced90dc7bdc491714e7febfa72e891cf18c6bc877767a3f3",
    "readme": "d984818da6f4639d1085a012c04d065ffe6243f7d2247188cfdc745287a694f8",
    "provenance_template": "1e2e42cfbe21db9b057f0b231f8c1836e3dca843f22e7f9e9a347288389e9b68",
    "raw_log_template": "fb0f2cf3cd69f78995efeab5a85a4fb4bbdff1e3a72fddf35e2d32dba20ed94f",
    "visual_template": "afcfdffa7f257ed2391c148a35c720a7a6a4d57b172a56a76f1a0f7e015eea42",
    "contact_sheet_template": "d73d9ea97eac9599c249fa6d1c6ac11ddd5e9588fd735010bb20465aaddd891b",
    "quality_template": "0954ed9eaffc9687c4ac851d8ab7a4b48a2d7c54343ebd3e633962ce5fe8a30b",
    "comment_template": "175e946242502100e4a99ab4cda8afec595c1d10d1a652873a4cb03c7cde4ec6",
    "merge_template": "d8c429d2b9b197e3ddc787d74c9b651e12b7e3c3a74737695b6ec5c194da16ca",
    "protected_checkout_template": "ad6dd9e2c93605b6d4bfe02218f67f6457a8a1bf18701d5527659620c99b1a46",
    "readbacks_template": "11dbcba84df854b1e3c58e0bf6bd1f8f6f72b400d51db9754a2b92a221881ded",
}
NYAY21_HISTORY_PURGE_FILES: dict[str, Path] = {
    "execution_tests": ROOT / "scripts/ci/test_nyay21_execution_time_seal.py",
    "execution_adversarial": ROOT / "scripts/ci/test_nyay21_execution_adversarial.py",
    "executor_adapters": ROOT / "scripts/ci/nyay21_executor_adapters.py",
    "executor_runtime": ROOT / "scripts/ci/nyay21_executor_runtime.py",
    "executor_adapter_tests": ROOT / "scripts/ci/test_nyay21_executor_adapters.py",
    "executor_runtime_tests": ROOT / "scripts/ci/test_nyay21_executor_runtime.py",
    "corrective_contracts": ROOT / "scripts/ci/nyay21_corrective_contracts.py",
    "execution_v2_preparation": ROOT / "docs/operations/nyay21-history-purge/EXECUTION_V2_PREPARATION.md",
    "gate": ROOT / "scripts" / "ci" / "nyay21_history_purge.py",
    "tests": ROOT / "scripts" / "ci" / "test_nyay21_history_purge.py",
    "path_to_go_tests": ROOT / "scripts" / "ci" / "test_nyay21_path_to_go.py",
    "contract": ROOT / "scripts" / "ci" / "nyay21_history_purge_contract.json",
    "execution_plan": (
        ROOT / "docs" / "operations" / "nyay21-history-purge" / "EXECUTION_PLAN.md"
    ),
    "backup_and_rollback": (
        ROOT
        / "docs"
        / "operations"
        / "nyay21-history-purge"
        / "BACKUP_AND_ROLLBACK.md"
    ),
    "collaborator_realignment": (
        ROOT
        / "docs"
        / "operations"
        / "nyay21-history-purge"
        / "COLLABORATOR_REALIGNMENT.md"
    ),
    "host_residual_surfaces": (
        ROOT
        / "docs"
        / "operations"
        / "nyay21-history-purge"
        / "HOST_RESIDUAL_SURFACES.md"
    ),
    "evidence_rebinding_manifest": (
        ROOT
        / "docs"
        / "operations"
        / "nyay21-history-purge"
        / "EVIDENCE_REBINDING_MANIFEST.json"
    ),
    "rewrite_execution_request": (
        ROOT
        / "docs"
        / "operations"
        / "nyay21-history-purge"
        / "REWRITE_EXECUTION_REQUEST.md"
    ),
    "authoritative_ref_seal": (
        ROOT / "docs" / "operations" / "nyay21-history-purge"
        / "AUTHORITATIVE_REF_SEAL_20260904.json"
    ),
    "ruleset_payload_pair": (
        ROOT / "docs" / "operations" / "nyay21-history-purge"
        / "RULESET_PAYLOAD_PAIR_20260904.json"
    ),
    "evidence_rebinding_manifest_r2": (
        ROOT / "docs" / "operations" / "nyay21-history-purge"
        / "EVIDENCE_REBINDING_MANIFEST_20260904.json"
    ),
    "ci_budget_memo": (
        ROOT / "docs" / "operations" / "nyay21-history-purge"
        / "CI_BUDGET_MEMO_20260904.json"
    ),
    "gpg_signature_disposition": (
        ROOT / "docs" / "operations" / "nyay21-history-purge"
        / "GPG_SIGNATURE_DISPOSITION.md"
    ),
}
EXPECTED_NYAY21_HISTORY_PURGE_SHA256: dict[str, str] = {
    "execution_tests": "faaa3cb5c312933eb01c55b78cb02dedeede22858b6dffd63f7fcd5e0afcccfa",
    "execution_adversarial": "0abf6a439fb24b8643ca4a18163ca701ee5a00fe6aa8cea35e5e0a1c4c65d752",
    "executor_adapters": "32ebcf83b1b634080f36887b2c382ef79382fe37d6b25d731d8ed39fff540475",
    "executor_runtime": "bfd916c333ff32d9bebd3d6054a3a2fc2233d7806ea206d1c75bef3478b74d2f",
    "executor_adapter_tests": "3f024d3edc948c01139c48ea9c9f16ca2b39726d19cfdf8b6ab78470c412cff3",
    "executor_runtime_tests": "5ed2d824767ac0762ed8e898d81f2df1fa43bf0466541f5368532c3a2b46e7d9",
    "corrective_contracts": "4aa124b454f4647de5a8ee93e4f8d76461c9fffa289f2b16df965554f5e60db7",
    "execution_v2_preparation": "e53cbf767eea658992363f21a3e31d234b1f5ef89a188340e1a9e04b1c31dff7",
    "gate": "9ad428d56b4217c613c13a8bd7e380c6a827b584204223359e0aab4cf652380c",
    "tests": "8a636cc714197203f3541b1d667bda7dde9785ec25012b3da1567d7618a7dfc0",
    "path_to_go_tests": "3aa103aa8dd0b2e95c30168d932a744e30bcbd178c1277fcff0a6d05222cf94f",
    "contract": "3f0e4fd5d8f1525f3a64c3c583f405816e27d4c728e1c21a2addadd1480dd0e1",
    "execution_plan": "fdd3a11587bc040d04460b3aa3038b170243cff86d7d3f3cf295433703cf7b00",
    "backup_and_rollback": "3e05560b32a9ba7d1549fec008ce89ac5f8539d416408f16399aa8e86043bcd5",
    "collaborator_realignment": "85303ca8884966389e89379d2f197f9135d46adf4125c944ef2a0fca53256279",
    "host_residual_surfaces": "39c54141c6499fc9db1ed4befd6ab517edada2cfc62fc8b0a0a5836293d59ae1",
    "evidence_rebinding_manifest": "583ccaa028ff21170faa878c503130d56a159b975491be4a4f79acc8b07638c5",
    "rewrite_execution_request": "c4991f36526730ef891f33a08e5170f7caafb63a71dc269f67f3b4163ec9967c",
    "authoritative_ref_seal": "87c09f04ef4db49333616f5bef2e66c4ee22f6314790e4364003d7600cd20b72",
    "ruleset_payload_pair": "9aaba28b2ea5aa2aeb2081f9aa724fcd97e73d5b8d7cca786bf6c7d92792cfcd",
    "evidence_rebinding_manifest_r2": "bbc25dc90eb0760cd473d5f2f447055a42b89a25bd28f557ce24b47a09e82fbb",
    "ci_budget_memo": "f4fa07b25bbb3797be2e43e87023a4ed68ecfc674c505b622647d3ecd6df3729",
    "gpg_signature_disposition": "2bf48fbf01930bbc0ee23654c950cd7d43846f5ba6aa9687862fe51230c8652c",
}
EXPECTED_NYAY14_POLICY_COMMAND = "python scripts/ci/test_nyay14_evidence_gate.py"
EXPECTED_NYAY14_SECURITY_POLICY_COMMAND = (
    "python scripts/ci/test_nyay14_evidence_gate_security.py"
)
EXPECTED_NYAY27_POLICY_COMMAND = "python scripts/ci/test_nyay27_contact_sheet_gate.py"
EXPECTED_NYAY21_POLICY_COMMAND = "python scripts/ci/test_nyay21_history_purge.py"
EXPECTED_NYAY21_PATH_TO_GO_POLICY_COMMAND = (
    "python scripts/ci/test_nyay21_path_to_go.py"
)
EXPECTED_NYAY33_POLICY_COMMAND = "python scripts/ci/test_nyay33_documentation_polish.py"
EXPECTED_NYAY22_POLICY_COMMAND = "python scripts/ci/test_nyay22_ci_policy.py"
EXPECTED_NYAY11_POLICY_COMMAND = "python scripts/ci/test_nyay11_ci_policy.py"
EXPECTED_NYAY4_BROWSER_GATE_SHA256 = (
    "2792f134f7ae64c4d83a2653d2c31fe07bf1b1fb0822a7b8373c1d72827e3d27"
)
EXPECTED_NYAY4_BROWSER_CONTRACT_SHA256 = (
    "3eaafebac1fa1b47fc7a8892add83ec9ee480d797224ad2472eacaca29e2b067"
)
EXPECTED_NYAY4_BROWSER_CONTRACT_TEST_SHA256 = (
    "8b581591d17550821c99d3a2194f079aaec55bd569782b03d4effec3e70c2c87"
)
EXPECTED_NYAY4_PACKAGE_COMMAND = "node scripts/nyay4-otp-browser-negative.mjs"
EXPECTED_NYAY22_BROWSER_GATE_SHA256 = (
    "978830c0505f32fba394d706e63c3126ab95cc0856c1f2859bf9156799379f1a"
)
EXPECTED_NYAY22_BROWSER_CONTRACT_SHA256 = (
    "74f8104513b9c20905c3fb9877d7552e174e42b4e0cc13bc7fb2a1a06e7a704e"
)
EXPECTED_NYAY22_BROWSER_CONTRACT_TEST_SHA256 = (
    "59058d04a42047d782fafe2008980526872eee18c572fb105a5322dbe2a353ae"
)
EXPECTED_NYAY22_BROWSER_HARNESS_ENTRY_SHA256 = (
    "44970893d886c3b506207bf995c387444e2925464fafeb0c8987e78b6c1ab339"
)
EXPECTED_NYAY22_BROWSER_FIXTURE_SHA256 = (
    "8df6cfb852d53ace3f8216a3754aba018efcad235c6d9f34c13a5fb4f5fc1d99"
)
EXPECTED_NYAY22_BROWSER_SEED_SHA256 = (
    "a1abaccc8c966792a1c7a174eede042b8a44ad35dfd0c8b4849c695a84ef0218"
)
EXPECTED_NYAY22_BROWSER_SEED_TEST_SHA256 = (
    "c22822224fcad6576fdf3097bfcb22b4cadfa6890419f94afc659bdb4e0ce939"
)
EXPECTED_NYAY22_POSTGRES_GATE_SHA256 = (
    "b4074d921ccb16a78c68d68b1d3633355171ec7599b667e41e5f1f182de560ce"
)
EXPECTED_NYAY22_POSTGRES_CONTRACT_SHA256 = (
    "c9de111f70ef238d942b2492983137ea850f1b2f7d5fc3869b447b1d52d4e880"
)
EXPECTED_NYAY22_SCHEMA_MIGRATION_SHA256 = (
    "d2a221b00ff785c2748cd7394a57da4cfd34596806078ccc815244626dcb7ce1"
)
EXPECTED_NYAY22_MENTOR_AUTH_MODEL_SHA256 = (
    "fee41f13b14cbf66fe74d5f643eed5706defa95e872042dd0eedbf1b52490e6d"
)
EXPECTED_NYAY22_MIGRATION_DISPATCH_TEST_SHA256 = (
    "a72a615282419faedd2f9930955b96a4c81616105f3eb8363229beee91394094"
)
EXPECTED_NYAY22_NYAY19_ERASURE_TEST_SHA256 = (
    "aacc42fa03b652a203d878f893336e5f34595fa4c557754134e80ae66e05e14f"
)
EXPECTED_NYAY22_POSTGRES_SCHEMA = "nyay22-mentor-postgres/v1"
EXPECTED_NYAY22_POSTGRES_ORACLES = (
    "MIGRATION_0023_UP_DOWN_UP_CHECK",
    "POSTGRES_BOUNDED_LOCKS_NO_DEADLOCK",
    "INITIATE_SAME_KEY_EXACT_REPLAY",
    "INITIATE_CHANGED_PAYLOAD_CONFLICT",
    "PROVIDER_SUBJECT_UNIQUE_INSERT",
    "EXCHANGE_K1_K2_ONE_AUTHORITY",
    "OWNER_LOGIN_EXCHANGE_CLASS_EXCLUSION",
    "ROTATE_REVOKE_LINEARIZED",
    "ROTATE_LOGOUT_LINEARIZED",
    "DELETION_VERIFY_REVOKE_BOTH_ORDERS",
    "DELETION_EXCHANGE_REVOKE_BOTH_ORDERS",
    "PROOF_REVOCATION_AUTHORITY_RACE",
    "SUBJECT_CONSENT_REVOCATION_AUTHORITY_RACE",
    "RETENTION_ADVISORY_NONOVERLAP",
    "RETENTION_ATOMIC_GRAPH_SEVERANCE",
    "RETENTION_OVERSIZE_FAIL_CLOSED",
    "AUDIT_APPEND_ONLY_AND_CREDENTIAL_PRIVACY",
)
EXPECTED_NYAY22_POSTGRES_ORACLE_INVENTORY_SHA256 = (
    "99ad80b085b29ff6f5eae3f04bfbbd3d2516af6c3c56333083d81ec5b3a0eab8"
)
EXPECTED_NYAY22_APPLICATION_HEAD = "0023_nyay22_mentor_ceremony"
EXPECTED_NYAY22_PREVIOUS_REVISION = "0022_nyay9_owner_profile_api"
EXPECTED_NYAY19_BROWSER_GATE_SHA256 = (
    "9becbdf0e47201eceed8fe36b1311be28a21831c7ffb14d81247b7fd137e89c4"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_SHA256 = (
    "9ef0368e4f3f8510256e94d23117a5eed1e188f0936167120d193aeb723c9591"
)
EXPECTED_NYAY19_BROWSER_CONTRACT_TEST_SHA256 = (
    "65cbfda5fa9ca1a813fbc54f256f28cf31858f068f28ab3827e27d9d30c44b9e"
)
EXPECTED_NYAY19_PACKAGE_COMMAND = "node scripts/nyay19-auth-lifecycle-browser.mjs"
EXPECTED_NYAY5_BROWSER_ORCHESTRATOR_SHA256 = (
    "284c881c90d9ce9617d6d907b1b959b4aed26f6a64c72b94baab0eb42e9f43cc"
)
EXPECTED_NYAY5_BROWSER_GATE_SHA256 = (
    "5ec659792697230444aa21b1d59fd93a1b389ad557b82386e13aca921d2db783"
)
EXPECTED_NYAY5_BROWSER_CONTRACT_SHA256 = (
    "b1dbbfefc9f85ac6d96d5849bff6e7491b8826d15e6514f6695b9c7af865160e"
)
EXPECTED_NYAY5_BROWSER_CONTRACT_TEST_SHA256 = (
    "797ee22a74559fdca56e8e43a6711227dfb6e979c3fabfc05f3326fbabeed32b"
)
EXPECTED_NYAY5_BROWSER_CONTROL_SHA256 = (
    "8cd17662b5d9c2973089a3733cea17eb1eb84a079d39547f13523952148c8274"
)
EXPECTED_NYAY5_POSTGRES_GATE_SHA256 = (
    "6d659081ec06b7c8e5fc0e213b2453e25520e04cd9e626f40c4d508fb2241197"
)
EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_SHA256 = (
    "319a7aace482b04ee97af4fe6ce9ae9234bbf428f64b4d8fd8ada2b4f6923181"
)
EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_TEST_SHA256 = (
    "a9e83bddb5ec55d095359c382991c5c9751f604ed8b682c888911d71ae40e9fa"
)
EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_SHA256 = (
    "98b2b033e87083d4d17246c57fe1765501dcba1cbb8bd2415a66631bcd2d5c32"
)
EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_TEST_SHA256 = (
    "8768b19f049a803981f37b0378a4e922c8f1c96e20a3fa7c62dbccb900adc13e"
)
EXPECTED_NYAY18_NAMESPACE_GATE_SHA256 = (
    "985eeaf3fdea31132d5889a2f0636af82d0378f2afd56937c89db315175da622"
)
EXPECTED_NYAY18_NAMESPACE_GATE_TEST_SHA256 = (
    "24b291e76ba641defc9e3ad77e646aee321adefe587a334a8d6e42476a94bdd9"
)
EXPECTED_NYAY18_NAMESPACE_CONTRACT_SHA256 = (
    "3eed575dbf58024ce2a662193b0c7eddd0cbae311e9e04a1a57534343aa60c17"
)
EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_SHA256 = (
    "4ea549791f349857460e6f65ba274aee81caa0031ed49a426585ff7fdf6e919c"
)
EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST_SHA256 = (
    "cb0133a5d7ab7e34314139212983c5f653d3624125d0ce5dd3da5782d1649368"
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_SHA256 = (
    "9eb4089410b79d6ef4fd786f79cf6ae92bedf8448ccdf4340ada54acc6da9592"
)
EXPECTED_NYAY18_BROWSER_GATE_SHA256 = (
    "39850c55d708250e072594825c893bf000d19f84b159d0af53ccb357b18adb67"
)
EXPECTED_NYAY18_BROWSER_PREVIEW_SERVER_SHA256 = (
    "5a42234e4be15a882d3e4154247b9bf2df96b0ce835f54daeb03d9f06ad25037"
)
EXPECTED_NYAY18_BROWSER_CONTRACT_SHA256 = (
    "3f155d91ef8874afa02197ec1aff1d0f6143c3d1ba93f1f7971ed958c095d8ca"
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_SHA256 = (
    "31d913674781c111d5365cb1fa175b8c0cad73d902cc115673d4b3b52f2a4140"
)
EXPECTED_NYAY18_BROWSER_PACKAGE_COMMAND = (
    "node scripts/nyay18-browser-namespace.mjs"
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_EXACT_HEAD = (
    'EXACT_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"',
    'EXACT_TREE="$(git -C "$ROOT" rev-parse \'HEAD^{tree}\')"',
    'PARENT_LINE="$(git -C "$ROOT" rev-list --parents -n 1 HEAD)"',
    'NYAY18_EXACT_COMMIT="$EXACT_COMMIT"',
    'NYAY18_EXACT_TREE="$EXACT_TREE"',
    'NYAY18_EXACT_PARENT="$EXACT_PARENT"',
    'NYAY18_PREVIEW_ROOT="$ROOT/frontend/dist"',
    'NYAY18_PREVIEW_PORT="$PORT"',
    "exec node scripts/nyay18-preview-server.mjs",
    "npm run qa:nyay18:browser-namespace",
)
EXPECTED_NYAY18_BROWSER_GATE_EXACT_HEAD = (
    "const EXACT_COMMIT = requiredEnv('NYAY18_EXACT_COMMIT');",
    "const EXACT_TREE = requiredEnv('NYAY18_EXACT_TREE');",
    "const EXACT_PARENT = requiredEnv('NYAY18_EXACT_PARENT');",
    "commitMatchesHead: initialGit.head === EXACT_COMMIT,",
    "treeMatchesHead: initialGit.tree === EXACT_TREE,",
    "parentMatchesHead: initialGit.parent === EXACT_PARENT,",
    "worktreeClean: initialGit.clean,",
    "exactCommit: EXACT_COMMIT,",
    "exactTree: EXACT_TREE,",
    "exactParent: EXACT_PARENT,",
    "const inspection = inspectNyay18Evidence(report);",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_EXACT_HEAD = (
    "'exactCommit', 'exactParent', 'exactTree'",
    "if (!COMMIT.test(report?.exactCommit ?? ''))",
    "if (!COMMIT.test(report?.exactTree ?? ''))",
    "if (report?.exactParent !== 'ROOT' && !COMMIT.test(report?.exactParent ?? ''))",
    "'bad-exact-commit'",
    "'bad-exact-tree'",
    "'bad-exact-parent'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_EXACT_HEAD = (
    "wrongTree.exactTree = 'bad';",
    "wrongParent.exactParent = 'bad';",
    "expect(source).toContain('exactTree: EXACT_TREE');",
    "expect(source).toContain('exactParent: EXACT_PARENT');",
)
EXPECTED_NYAY18_BROWSER_PREVIEW_SEMANTICS = (
    "const HOST = '127.0.0.1';",
    "requiredEnv('NYAY18_PREVIEW_ROOT')",
    "requiredEnv('NYAY18_PREVIEW_PORT')",
    "if (!path.isAbsolute(rootInput))",
    "if (relative.startsWith('..') || path.isAbsolute(relative)) return null;",
    "if (method !== 'GET' && method !== 'HEAD')",
    "if (pathname === METRICS_PATH)",
    "if (pathname === HOSTILE_ASSET_PATH)",
    "if (request.headers.cookie) metrics.hostileAssetCookieHeaders += 1;",
    "'Cache-Control': 'private, no-store'",
    "Vary: 'Cookie'",
    "PRIVATE_SENTINEL",
    "server.listen(PORT, HOST);",
)
EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_PREVIEW_DIGEST = (
    "PREVIEW_SOURCE_SHA256=",
    "hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()",
    '"$ROOT/frontend/scripts/nyay18-preview-server.mjs"',
    'NYAY18_PREVIEW_SOURCE_SHA256="$PREVIEW_SOURCE_SHA256"',
)
EXPECTED_NYAY18_BROWSER_GATE_PREVIEW_DIGEST = (
    "const PREVIEW_SOURCE_SHA256 = requiredEnv('NYAY18_PREVIEW_SOURCE_SHA256');",
    "path.resolve(REPOSITORY, 'frontend/scripts/nyay18-preview-server.mjs')",
    "previewSourceMatches: previewSourceActual === PREVIEW_SOURCE_SHA256,",
    "previewServerSourceSha256: PREVIEW_SOURCE_SHA256,",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_PREVIEW_DIGEST = (
    "'previewServerSourceSha256'",
    "if (!digest(report?.previewServerSourceSha256))",
    "'bad-preview-server-source-sha'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_PREVIEW_DIGEST = (
    "wrongPreviewSource.previewServerSourceSha256 = 'bad';",
    "expect(source).toContain('previewServerSourceSha256: PREVIEW_SOURCE_SHA256');",
    "'bad-preview-server-source-sha'",
)
EXPECTED_NYAY18_BROWSER_PREVIEW_INSTALL_SHELL = (
    "const ARM_SHELL_PATH = '/__nyay18-gate/arm-shell';",
    "const PRIVATE_SHELL_SENTINEL = 'nyay18-private-shell-sentinel';",
    "hostileShellCookieHeaders: 0",
    "hostileShellServerRequests: 0",
    "if (pathname === ARM_SHELL_PATH)",
    "hostileShellArmed = true;",
    "if (pathname === '/index.html' && hostileShellArmed)",
    "metrics.hostileShellServerRequests += 1;",
    "if (request.headers.cookie) metrics.hostileShellCookieHeaders += 1;",
)
EXPECTED_NYAY18_BROWSER_GATE_INSTALL_SHELL = (
    "fetch('/__nyay18-gate/arm-shell'",
    "hostileShellServerRequests === 1",
    "hostileShellCookieHeaders === 0",
    "privateCache.hostileShellEntries === 0",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_INSTALL_SHELL = (
    "metrics.hostileShellServerRequests === 1",
    "metrics.hostileShellCookieHeaders === 0",
    "metrics.hostileShellEntries === 0",
    "'unexercised-hostile-shell-probe'",
    "'cookie-bearing-hostile-shell-fetch'",
    "'cached-hostile-private-shell'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_INSTALL_SHELL = (
    "'unexercised-hostile-shell-probe'",
    "'cookie-bearing-hostile-shell-fetch'",
    "'cached-hostile-private-shell'",
    "'hostileShellCookieHeaders'",
    "'hostileShellServerRequests'",
)
EXPECTED_NYAY18_BROWSER_GATE_TWO_REALM_PRIVACY = (
    "const migration = instrumentationCanaries.migration;",
    "const final = instrumentationCanaries.final;",
    "const sumAcrossDocuments = (key) => migration[key] + browser[key];",
    (
        "const detectedInBothDocuments = (key) => migration[key] === true "
        "&& final[key] === true;"
    ),
    "Number(migration.probeAvailable === true) + Number(final.probeAvailable === true)",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TWO_REALM_PRIVACY = (
    "metrics.instrumentationDocumentCount === 2",
    "'privacy-instrumentation-canary-missed'",
    "'single-privacy-probe-document'",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_TWO_REALM_PRIVACY = (
    "metrics.instrumentationDocumentCount = 1;",
    "'privacy-instrumentation-canary-missed'",
    "'single-privacy-probe-document'",
    "'migrationPrivacyInstrumentation'",
)
EXPECTED_NYAY18_BROWSER_GATE_FINITE_LEADING_PURGE = (
    "NYAY18_LEADING_CANDIDATE_KEYS",
    "NYAY18_LEADING_TARGET_KEYS",
    "targetIndexBeforeBootstrap >= NYAY18_LEADING_UNRELATED_KEYS",
    "unrelatedBeforeTarget >= NYAY18_LEADING_UNRELATED_KEYS",
    "targetSurvivorsBeforeBootstrap === 1",
    "&& leading.leadingBeforeOwned && leading.targetRemoved && leading.valuesExact",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_FINITE_LEADING_PURGE = (
    "'leading-target-survived'",
    "'targetRemoved', 'targetSurvivorsBeforeBootstrap', 'unrelatedBeforeTarget',",
    "&& metrics.targetRemoved === true",
    "&& metrics.targetSurvivorsBeforeBootstrap === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_FINITE_LEADING_PURGE = (
    "'leading-target-survived'",
    "metrics.targetRemoved = false;",
    "metrics.targetIndexBeforeBootstrap = 256;",
)
EXPECTED_NYAY18_BROWSER_GATE_ACTOR_ROTATION = (
    "const actorRotationResponse = name === 'actor_rotation'",
    "await actorRotationResponse;",
    "actorRotationRediscoveryResponses = 1;",
    "&& lifecycle.actorRotationRediscoveryResponses === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_ACTOR_ROTATION = (
    "'actor-rotation-unobserved'",
    "'actorRotation', 'actorRotationRediscoveryResponses',",
    "&& metrics.actorRotationRediscoveryResponses === 1",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_ACTOR_ROTATION = (
    "'actor-rotation-unobserved'",
    "metrics.actorRotationRediscoveryResponses = 0;",
    "'actorRotationRediscoveryResponses'",
)
EXPECTED_NYAY18_BROWSER_GATE_AUTHORITY_TRANSITIONS = (
    "'logout', 'expiry', 'deletion', 'revocation', 'canonical_loss',",
    "surface.transitionStarts === 1 && surface.transitionEnds === 1",
    "lifecycle.transitionStarts === 5 && lifecycle.transitionEnds === 5",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_AUTHORITY_TRANSITIONS = (
    "'lifecycle-missing-transition'",
    "&& metrics.transitionStarts === 5",
    "&& metrics.transitionEnds === 5",
)
EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_AUTHORITY_TRANSITIONS = (
    "'lifecycle-missing-transition'",
)
EXPECTED_NYAY5_BROWSER_PACKAGE_COMMAND = "node scripts/nyay5-profile-browser.mjs"
EXPECTED_NYAY5_ACCEPTANCE_PACKAGE_COMMAND = (
    "node scripts/nyay5-acceptance-aggregate.mjs"
)
NYAY19_ISOLATED_MIGRATION_ENV = "NYAY19_ISOLATED_MIGRATION_EXECUTE"
EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS: dict[
    tuple[str, str], tuple[str, ...]
] = {
    (
        "ci-flaky-nyay4-cookie-reload-symmetry.yml",
        "postgres-16-pgvector-cookie-origin-reload",
    ): (
        "python scripts/nyay4_postgres_otp_gate.py",
    ),
    ("registration-db-gate.yml", "postgres-16-pgvector"): (
        "bash scripts/db_gate.sh",
    ),
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): (
        "bash scripts/db_gate.sh",
        "python -m alembic upgrade head",
    ),
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): (
        "bash scripts/wave2_db_gate.sh",
    ),
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): (
        "bash scripts/db_gate.sh",
    ),
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): (
        "bash scripts/wave4_db_gate.sh",
    ),
    ("wave5-calendar-gate.yml", "calendar-postgres"): (
        "python scripts/wave5_postgres_gate.py",
    ),
    ("wave5-calendar-gate.yml", "calendar-real-browser"): (
        "alembic upgrade head",
    ),
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): (
        "bash scripts/db_gate.sh",
    ),
}
EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS = {
    "backend/tests/nyay12_native_gate.py",
    "backend/scripts/nyay2_postgres_authorization_gate.py",
    "backend/scripts/nyay3_postgres_characterization.py",
    "backend/scripts/nyay4_postgres_otp_gate.py",
    "backend/scripts/nyay5_postgres_profile_gate.py",
    "backend/scripts/nyay9_postgres_profile_gate.py",
    "backend/scripts/nyay11_postgres_authority_gate.py",
    "backend/scripts/nyay16_postgres_gate.py",
    "backend/scripts/nyay17_postgres_idempotency_gate.py",
    "backend/scripts/nyay19_migrate.py",
    "backend/scripts/nyay19_postgres_auth_retention_gate.py",
    "backend/scripts/nyay22_postgres_mentor_gate.py",
    "backend/scripts/wave2_postgres_gate.py",
    "backend/scripts/wave4_postgres_gate.py",
    "backend/scripts/wave5_postgres_gate.py",
}
EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS = {
    "backend/scripts/db_gate.sh": "isolated-postgresql",
    "scripts/nyay5_profile_browser_gate.sh": "nyay5-owned-scratch-postgresql",
    "scripts/wave2_tutoring_browser_gate.sh": "local-sqlite",
}
NYAY19_ISOLATED_DATABASE_MARKERS = {
    "ci",
    "gate",
    "nyay2",
    "nyay3",
    "nyay4",
    "nyay16",
    "nyay17",
    "nyay19",
    "qa",
    "scratch",
    "test",
    "testing",
    "w2gate",
}
NYAY19_FORBIDDEN_DATABASE_MARKERS = {"prod", "production", "stage", "staging"}
NYAY19_ISOLATED_APP_ENVS = {
    "development",
    "dev",
    "local",
    "test",
    "testing",
    "stage",
    "staging",
}
EXPECTED_DB_GATE_SHA256 = "b1e2358ebe6230721fb8106cac4eb4cb7f4f613ad1c3df10b2002760f8694076"
EXPECTED_ISOLATED_BACKEND_PYTEST_COMMAND = (
    "env -u DATABASE_URL -u CORS_ORIGINS "
    "-u MENTOR_TERMINAL_RETENTION_SECONDS "
    "-u MENTOR_AUDIT_LINK_RETENTION_SECONDS "
    '-u MENTOR_RETENTION_MODE APP_ENV=testing "$PY" -m pytest -q'
)
EXPECTED_NYAY16_DB_GATE_COMMAND = (
    'NYAY16_GATE_ALLOW_DATABASES=true "$PY" scripts/nyay16_postgres_gate.py '
    "--output test-results/nyay16-postgres/summary.json"
)
EXPECTED_NYAY3_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay3_postgres_characterization.py '
    "--expect hardened --output test-results/nyay3-postgres/summary.json"
)
EXPECTED_NYAY2_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay2_postgres_authorization_gate.py '
    "--report test-results/nyay2-postgres/summary.json"
)
EXPECTED_NYAY5_DB_GATE_COMMAND = (
    'NYAY5_POSTGRES_GATE=1 "$PY" scripts/nyay5_postgres_profile_gate.py '
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay5-postgres/summary.json"
)
EXPECTED_NYAY9_DB_GATE_COMMAND = (
    'NYAY9_POSTGRES_GATE=1 node ../scripts/ci/nyay9-profile-api-postgres.mjs '
    '--execute --python "$PY" --database-url "$DATABASE_URL" '
    "--producer-output test-results/nyay9-postgres/producer-summary.json "
    "--output test-results/nyay9-postgres/summary.json"
)
EXPECTED_NYAY17_DB_GATE_COMMAND = (
    '"$PY" scripts/nyay17_postgres_idempotency_gate.py '
    "--report test-results/nyay17-postgres/summary.json"
)
EXPECTED_NYAY4_DB_GATE_COMMAND = (
    'NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py '
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay4-postgres/summary.json"
)
EXPECTED_NYAY19_DB_GATE_COMMAND = (
    'NYAY19_POSTGRES_GATE_EXECUTE=1 "$PY" '
    "scripts/nyay19_postgres_auth_retention_gate.py "
    '--execute --database-url "$DATABASE_URL" '
    "--output test-results/nyay19-postgres/summary.json"
)
EXPECTED_NYAY22_DB_GATE_COMMAND = (
    'NYAY22_POSTGRES_GATE=1 "$PY" scripts/nyay22_postgres_mentor_gate.py '
    '--database-url "$DATABASE_URL" '
    "--output test-results/nyay22-postgres/summary.json"
)
EXPECTED_NYAY11_DB_GATE_BLOCK = (
    'echo "== NYAY-11 guardian/institutional authority gate (PostgreSQL 16 + pgvector) =="\n'
    "mkdir -p test-results/nyay11-postgres\n"
    'NYAY11_POSTGRES_GATE=1 "$PY" scripts/nyay11_postgres_authority_gate.py \\\n'
    '  --database-url "$DATABASE_URL" \\\n'
    "  --output test-results/nyay11-postgres/summary.json\n"
)
EXPECTED_NYAY22_DB_GATE_STAGE = (
    'echo "== NYAY-22 mentor ceremony concurrency/lifecycle gate '
    '(PostgreSQL 16 + pgvector) =="\n'
    "mkdir -p test-results/nyay22-postgres\n"
    'NYAY22_POSTGRES_GATE=1 "$PY" scripts/nyay22_postgres_mentor_gate.py \\\n'
    '  --database-url "$DATABASE_URL" \\\n'
    "  --output test-results/nyay22-postgres/summary.json\n"
)
EXPECTED_NYAY22_DB_GATE_EVIDENCE_PROMOTION = (
    "mkdir -p \"$REPO_ROOT/test-results/nyay22-postgres\"\n"
    "cp test-results/nyay22-postgres/summary.json \\\n"
    '  "$REPO_ROOT/test-results/nyay22-postgres/summary.json"\n'
)
EXPECTED_NYAY22_BROWSER_PACKAGE_COMMAND = (
    "node scripts/nyay22-mentor-ceremony-browser.mjs"
)
EXPECTED_NYAY22_LIVE_SEED_STEP = (
    "      - name: Seed private server-owned NYAY-22 live browser fixture\n"
    "        working-directory: backend\n"
    "        env:\n"
    "          APP_ENV: test\n"
    '          NYAY22_BROWSER_FIXTURE_SEED: "1"\n'
    "        run: >-\n"
    "          python scripts/seed_nyay22_browser_fixture.py\n"
    '          --output "$RUNNER_TEMP/nyay22-live-fixture.json"\n\n'
)
EXPECTED_NYAY22_BROWSER_STEP = (
    "      - name: NYAY-22 production Chromium mentor-authority gate\n"
    "        working-directory: frontend\n"
    "        env:\n"
    "          NYAY22_BROWSER_EVIDENCE_PATH: ${{ github.workspace }}/test-results/nyay22-browser/results.json\n"
    "          NYAY22_BROWSER_FAILURE_PATH: ${{ github.workspace }}/test-results/nyay22-browser/failure.json\n"
    '          NYAY22_BROWSER_PRODUCTION_BUILD: "true"\n'
    '          NYAY22_BROWSER_WEB_PORT: "1190"\n'
    "          NYAY22_LIVE_API_BASE_URL: http://127.0.0.1:1171\n"
    "          NYAY22_LIVE_FIXTURE_PATH: ${{ runner.temp }}/nyay22-live-fixture.json\n"
    "        run: npm run qa:nyay22:mentor-ceremony\n\n"
)
EXPECTED_NYAY22_FAILURE_UPLOAD_STEP = (
    "      - name: Upload privacy-safe NYAY-22 Chromium failure diagnostic\n"
    "        if: ${{ failure() && hashFiles('test-results/nyay22-browser/failure.json') != '' }}\n"
    "        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2\n"
    "        with:\n"
    "          name: nyay22-mentor-browser-failure-diagnostic\n"
    "          path: ${{ github.workspace }}/test-results/nyay22-browser/failure.json\n"
    "          if-no-files-found: error\n"
    "          retention-days: 14\n"
    "          include-hidden-files: false\n\n"
)
ACTION_REF = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
IMAGE_REF = re.compile(r"^\s*image:\s*([^\s#]+)", re.MULTILINE)
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PINNED_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
PINNED_SETUP_NODE_ACTION = (
    "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"
)
EXPECTED_NYAY4_SETUP_NODE_WITH = {
    "node-version": "22",
    "cache": "npm",
    "cache-dependency-path": "frontend/package-lock.json",
}
ALLOWED_SERVICE_IMAGE_REFS = {
    "clamav/clamav@sha256:78810772a92b4a9168115bc6b2e0ffd702640893b9577f8c3d0432762d2655c4",
    "pgvector/pgvector@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b",
}
ALLOWED_RUNNERS = {"ubuntu-24.04"}
ALLOWED_ACTIONS = {
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    PINNED_SETUP_NODE_ACTION,
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
}
REQUIRED_WORKFLOW_FILES = {
    "nyay18-frontend-namespace-gate.yml",
    "nyayone-policy-gate.yml",
    "registration-db-gate.yml",
    "wave1-foundation-gate.yml",
    "wave2-tutoring-db-gate.yml",
    "wave3-credential-trust-gate.yml",
    "wave4-private-reporting-gate.yml",
    "wave5-calendar-gate.yml",
    "nyay5-profile-boundary-gate.yml",
}
NYAY4_QUARANTINE_WORKFLOW_FILE = (
    "ci-flaky-nyay4-cookie-reload-symmetry.yml"
)
CANONICAL_WORKFLOW_FILES = REQUIRED_WORKFLOW_FILES | {
    NYAY4_QUARANTINE_WORKFLOW_FILE,
    "nyay13-independent-qa-observe.yml",
    "nyay42-optimization-observe.yml",
}
NYAY4_QUARANTINED_ASSERTION_ID = (
    "CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY"
)
NYAY4_QUARANTINE_REASON = (
    "Timing-sensitive reload-symmetry assertion that passes locally (17/17) "
    "but exhibits nondeterministic scheduling variance in GitHub Actions "
    "runners. Quarantined 2026-08-24 after Cycle 4. Product code is correct; "
    "CI runner timing is the variable."
)
DANGEROUS_ENV_KEYS = {
    "BASH_ENV",
    "ENV",
    "GITHUB_ENV",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "NODE_OPTIONS",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "RUBYOPT",
    "SHELLOPTS",
}
EXPECTED_UPLOAD_IF = (
    "${{ always() && steps.evidence_prepare.outcome == 'success' && "
    "steps.evidence_manifest.outcome == 'success' && "
    "steps.evidence_privacy.outcome == 'success' && "
    "steps.evidence_integrity.outcome == 'success' && "
    "steps.evidence_schema.outcome == 'success' }}"
)
EXPECTED_NYAY18_UPLOAD_IF = (
    "${{ always() && steps.browser_producer.outcome == 'success' && "
    "steps.browser_raw_manifest.outcome == 'success' && "
    "steps.browser_raw_integrity.outcome == 'success' && "
    "steps.browser_prepare.outcome == 'success' && "
    "steps.browser_manifest.outcome == 'success' && "
    "steps.browser_privacy.outcome == 'success' && "
    "steps.browser_integrity.outcome == 'success' }}"
)
EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN: tuple[dict[str, object], ...] = (
    {
        "name": "Run exact-head production Chromium namespace producer",
        "id": "browser_producer",
        "run": (
            "bash scripts/nyay18_browser_namespace_gate.sh "
            '"$RUNNER_TEMP/nyay18-browser-raw/results.json"'
        ),
    },
    {
        "name": "Seal raw Chromium evidence inventory",
        "id": "browser_raw_manifest",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$RUNNER_TEMP/nyay18-browser-raw"'
        ),
    },
    {
        "name": "Reverify raw Chromium evidence inventory",
        "id": "browser_raw_integrity",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --verify '
            '"$RUNNER_TEMP/nyay18-browser-raw"'
        ),
    },
    {
        "name": "Prepare privacy-safe textual Chromium attestation",
        "id": "browser_prepare",
        "run": (
            'mkdir -p "$RUNNER_TEMP/nyay18-browser-uploadable"\n'
            'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/results.json" '
            '"$RUNNER_TEMP/nyay18-browser-uploadable/results.json"\n'
            'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/SHA256SUMS.txt" '
            '"$RUNNER_TEMP/nyay18-browser-uploadable/RAW-SHA256SUMS.txt"\n'
        ),
    },
    {
        "name": "Seal uploadable Chromium attestation",
        "id": "browser_manifest",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Scan textual Chromium attestation for privacy regressions",
        "id": "browser_privacy",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/scan_evidence.py '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Reverify immutable uploadable Chromium attestation",
        "id": "browser_integrity",
        "if": "${{ always() }}",
        "run": (
            'python scripts/ci/evidence_manifest.py --verify '
            '"$RUNNER_TEMP/nyay18-browser-uploadable"'
        ),
    },
    {
        "name": "Upload NYAY-18 Chromium evidence",
        "if": EXPECTED_NYAY18_UPLOAD_IF,
        "uses": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "with": {
            "name": "nyay18-browser-namespace-attestation",
            "path": "${{ runner.temp }}/nyay18-browser-uploadable",
            "if-no-files-found": "error",
            "retention-days": "14",
            "include-hidden-files": "false",
        },
    },
)
EXPECTED_REQUIRED_RUN = """python - <<'PY'
import json, os, sys
results = {
    name: value["result"]
    for name, value in json.loads(os.environ["RESULTS"]).items()
}
print(results)
if not results or any(value != "success" for value in results.values()):
    sys.exit("one or more required jobs did not succeed")
PY"""
EXPECTED_NYAY19_START_RUN = (
    "(cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 1181 "
    '> "$RUNNER_TEMP/nyay19-backend.log" 2>&1 &)\n'
    "(cd frontend && npm run dev -- --host 127.0.0.1 --port 1180 --strictPort "
    '> "$RUNNER_TEMP/nyay19-frontend.log" 2>&1 &)\n'
    "for url in \\\n"
    "  http://127.0.0.1:1181/health \\\n"
    "  http://127.0.0.1:1180; do\n"
    "  for attempt in {1..60}; do\n"
    '    curl --fail --silent "$url" >/dev/null && break\n'
    '    if [[ "$attempt" == 60 ]]; then\n'
    '      echo "Timed out waiting for $url"\n'
    "      exit 1\n"
    "    fi\n"
    "    sleep 1\n"
    "  done\n"
    "done\n"
)
EXPECTED_NYAY5_ATTESTATION_RUN = (
    'python scripts/ci/nyay5_acceptance_attestations.py --browser '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json" '
    '--orchestrator '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/orchestrator-summary.json" '
    '--postgres "$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json" '
    '--otp-postgres "$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json" '
    '--manifest-root "$GITHUB_WORKSPACE/test-results/nyay5-browser" '
    '--output "$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json"'
)
EXPECTED_NYAY5_ACCEPTANCE_RUN = (
    'npm run qa:nyay5:acceptance -- --browser '
    '"$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json" '
    '--postgres "$GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json" '
    '--otp-postgres "$GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json" '
    '--attestations '
    '"$GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json" '
    '--output "$GITHUB_WORKSPACE/test-results/nyay5-acceptance/summary.json"'
)
EXPECTED_EXACT_STEPS: dict[tuple[str, str, str], dict[str, object]] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
        "Prove the browser evidence contract and planted mutants",
    ): {
        "name": "Prove the browser evidence contract and planted mutants",
        "working-directory": "frontend",
        "run": "npm test -- --run scripts/lib/nyay18-browser-contract.test.mjs",
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Seal and verify raw NYAY-5 browser evidence inventory",
    ): {
        "name": "Seal and verify raw NYAY-5 browser evidence inventory",
        "run": (
            'python scripts/ci/evidence_manifest.py --seal '
            '"$GITHUB_WORKSPACE/test-results/nyay5-browser"'
        ),
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Produce executed NYAY-5 acceptance attestations",
    ): {
        "name": "Produce executed NYAY-5 acceptance attestations",
        "run": EXPECTED_NYAY5_ATTESTATION_RUN,
    },
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
        "Run and require exact NYAY-5 acceptance aggregate PASS",
    ): {
        "name": "Run and require exact NYAY-5 acceptance aggregate PASS",
        "working-directory": "frontend",
        "run": EXPECTED_NYAY5_ACCEPTANCE_RUN,
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "NYAY-22 production Chromium mentor-authority gate",
    ): {
        "name": "NYAY-22 production Chromium mentor-authority gate",
        "working-directory": "frontend",
        "env": {
            "NYAY22_BROWSER_EVIDENCE_PATH": (
                "${{ github.workspace }}/test-results/nyay22-browser/results.json"
            ),
            "NYAY22_BROWSER_FAILURE_PATH": (
                "${{ github.workspace }}/test-results/nyay22-browser/failure.json"
            ),
            "NYAY22_BROWSER_PRODUCTION_BUILD": "true",
            "NYAY22_BROWSER_WEB_PORT": "1190",
            "NYAY22_LIVE_API_BASE_URL": "http://127.0.0.1:1171",
            "NYAY22_LIVE_FIXTURE_PATH": "${{ runner.temp }}/nyay22-live-fixture.json",
        },
        "run": "npm run qa:nyay22:mentor-ceremony",
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "Seed private server-owned NYAY-22 live browser fixture",
    ): {
        "name": "Seed private server-owned NYAY-22 live browser fixture",
        "working-directory": "backend",
        "env": {
            "APP_ENV": "test",
            "NYAY22_BROWSER_FIXTURE_SEED": "1",
        },
        "run": (
            "python scripts/seed_nyay22_browser_fixture.py "
            '--output "$RUNNER_TEMP/nyay22-live-fixture.json"'
        ),
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "NYAY-4 OTP authority Chromium regression",
    ): {
        "name": "NYAY-4 OTP authority Chromium regression",
        "working-directory": "frontend",
        "env": {
            "NYAY4_WEB_BASE_URL": "http://127.0.0.1:1170",
            "NYAY4_API_BASE_URL": "http://127.0.0.1:1171",
            "NYAY4_OTP_CAPTURE_URL": "http://127.0.0.1:1099",
        },
        "run": "npm run qa:nyay4:otp-negative",
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "Start NYAY-19 isolated auth lifecycle backend and frontend",
    ): {
        "name": "Start NYAY-19 isolated auth lifecycle backend and frontend",
        "env": {
            "APP_ENV": "test",
            "CORS_ORIGINS": '["http://127.0.0.1:1180"]',
            "OTP_DELIVERY_ENABLED": "true",
            "OTP_PROVIDER": "http",
            "OTP_PROVIDER_URL": "http://127.0.0.1:1099/send",
            "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
            "OTP_RESEND_COOLDOWN_SECONDS": "1",
            "OTP_FLOW_TTL_SECONDS": "600",
            "OTP_RECOVERY_PROOF_TTL_SECONDS": "300",
            "AUTH_SESSION_TTL_SECONDS": "20",
            "VITE_API_BASE_URL": "http://127.0.0.1:1181",
        },
        "run": EXPECTED_NYAY19_START_RUN,
    },
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
        "NYAY-19 authentication lifecycle Chromium regression",
    ): {
        "name": "NYAY-19 authentication lifecycle Chromium regression",
        "working-directory": "frontend",
        "env": {
            "NYAY19_WEB_BASE_URL": "http://127.0.0.1:1180",
            "NYAY19_API_BASE_URL": "http://127.0.0.1:1181",
            "NYAY19_OTP_CAPTURE_URL": "http://127.0.0.1:1099",
            "NYAY19_SESSION_TTL_SECONDS": "20",
            "NYAY19_OTP_RESEND_COOLDOWN_SECONDS": "1",
            "NYAY19_OTP_FLOW_TTL_SECONDS": "600",
            "NYAY19_RECOVERY_PROOF_TTL_SECONDS": "300",
        },
        "run": "npm run qa:nyay19:auth-lifecycle",
    },
}
EVIDENCE_CONTRACTS: dict[str, dict[str, tuple[str, str, str]]] = {
    "nyay5-profile-boundary-gate.yml": {
        "profile-postgres-production-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/nyay5-uploadable",
            "nyay5",
        ),
    },
    "wave1-foundation-gate.yml": {
        "frontend-native": (
            "$RUNNER_TEMP/v34-s11-s26",
            "$RUNNER_TEMP/v34-s11-s26-uploadable",
            "wave1",
        ),
    },
    "wave2-tutoring-db-gate.yml": {
        "wave2-postgres-16-pgvector": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave2-uploadable",
            "wave2",
        ),
    },
    "wave3-credential-trust-gate.yml": {
        "credential-trust-postgres-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave3-uploadable",
            "wave3",
        ),
    },
    "wave4-private-reporting-gate.yml": {
        "private-reporting-postgres-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave4-uploadable",
            "wave4",
        ),
    },
    "wave5-calendar-gate.yml": {
        "calendar-postgres": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave5-postgres-uploadable",
            "wave5-postgres",
        ),
        "calendar-real-browser": (
            "$GITHUB_WORKSPACE/test-results",
            "$RUNNER_TEMP/wave5-real-uploadable",
            "wave5-real",
        ),
    },
}
EXPECTED_JOB_DEFAULTS: dict[tuple[str, str], dict[str, object]] = {
    (
        "ci-flaky-nyay4-cookie-reload-symmetry.yml",
        "postgres-16-pgvector-cookie-origin-reload",
    ): {
        "run": {"working-directory": "backend"},
    },
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "run": {"working-directory": "backend"},
    },
    ("wave1-foundation-gate.yml", "frontend-native"): {
        "run": {"working-directory": "frontend"},
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "run": {"working-directory": "backend"},
    },
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): {
        "run": {"working-directory": "backend"},
    },
}
EXPECTED_JOB_ENVS: dict[tuple[str, str], dict[str, object]] = {
    (
        "ci-flaky-nyay4-cookie-reload-symmetry.yml",
        "postgres-16-pgvector-cookie-origin-reload",
    ): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_nyay4_flaky_ci",
        "REGISTRATION_SECRET": "ci-nyay4-flaky-encryption-secret",
        "REGISTRATION_LOOKUP_SECRET": "ci-nyay4-flaky-lookup-secret",
        "APP_ENV": "test",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        "QUARANTINED_ASSERTION_ID": NYAY4_QUARANTINED_ASSERTION_ID,
        "QUARANTINE_REASON": NYAY4_QUARANTINE_REASON,
    },
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_nyay5_ci",
        "NYAY5_POSTGRES_CONTROL_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_nyay5_ci",
        "APP_ENV": "testing",
        "REGISTRATION_SECRET": "ci-nyay5-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-nyay5-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret",
        "APP_ENV": "test",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:1032/nyayone_ci",
        "APP_ENV": "staging",
        "MENTOR_TERMINAL_RETENTION_SECONDS": "2592000",
        "MENTOR_AUDIT_LINK_RETENTION_SECONDS": "2592000",
        "MENTOR_RETENTION_MODE": "bounded_crypto_erasure",
        "CORS_ORIGINS": '["https://ci.nyayone.example"]',
        "CALENDAR_PUBLIC_BASE_URL": "https://calendar.example.test",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "REGISTRATION_SECRET": "ci-registration-secret-not-a-dev-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-dev-default",
        "OTP_DELIVERY_ENABLED": "true",
        "OTP_PROVIDER": "http",
        "OTP_PROVIDER_URL": "https://otp-provider.example.test/send",
        "OTP_PROVIDER_TOKEN": "ci-otp-provider-token-not-a-default",
        "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "APP_ENV": "test",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_ci",
        "APP_ENV": "staging",
        "MENTOR_TERMINAL_RETENTION_SECONDS": "2592000",
        "MENTOR_AUDIT_LINK_RETENTION_SECONDS": "2592000",
        "MENTOR_RETENTION_MODE": "bounded_crypto_erasure",
        "CALENDAR_PUBLIC_BASE_URL": "https://calendar.example.test",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "CREDENTIAL_TOKEN_SECRET": "ci-credential-token-secret-not-a-default",
        "CREDENTIAL_STORAGE_ROOT": "${{ github.workspace }}/test-results/credential-objects",
        "CREDENTIAL_PUBLIC_BASE_URL": "https://verify.example.test/verify",
        "CORS_ORIGINS": '["https://ci.nyayone.example"]',
        "OTP_DELIVERY_ENABLED": "true",
        "OTP_PROVIDER": "http",
        "OTP_PROVIDER_URL": "https://otp-provider.example.test/send",
        "OTP_PROVIDER_TOKEN": "ci-otp-provider-token-not-a-default",
        "OTP_PROVIDER_SUPPORTS_IDEMPOTENCY": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave4_qa",
        "TEST_DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave4_qa",
        "APP_ENV": "testing",
        "WAVE4_GATE_ALLOW_MUTATION": "true",
        "INTERNSHIP_RISK_LABELS_ENABLED": "false",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "INTERNSHIP_REPORT_STORAGE_ROOT": "${{ github.workspace }}/test-results/report-evidence",
        "INTERNSHIP_REPORT_SCANNER_PROVIDER": "clamav",
        "INTERNSHIP_REPORT_CLAMAV_HOST": "127.0.0.1",
        "INTERNSHIP_REPORT_CLAMAV_PORT": "3310",
        "CORS_ORIGINS": '["http://127.0.0.1:1260","http://localhost:1260","http://127.0.0.1:1263","http://localhost:1263"]',
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave5-calendar-gate.yml", "calendar-postgres"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave5_qa",
        "APP_ENV": "testing",
        "WAVE5_GATE_ALLOW_MUTATION": "true",
        "REGISTRATION_SECRET": "ci-registration-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-registration-lookup-secret-not-a-default",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
    ("wave5-calendar-gate.yml", "calendar-real-browser"): {
        "DATABASE_URL": "postgresql+psycopg://nyayone_ci:nyayone_ci_ephemeral@127.0.0.1:5432/nyayone_wave5_browser_qa",
        "APP_ENV": "testing",
        "WAVE5_E2E_ALLOW_SEED": "true",
        "REGISTRATION_SECRET": "ci-wave5-browser-encryption-secret-not-a-default",
        "REGISTRATION_LOOKUP_SECRET": "ci-wave5-browser-lookup-secret-not-a-default",
        "CORS_ORIGINS": '["https://127.0.0.1:1290"]',
        "CALENDAR_PUBLIC_BASE_URL": "https://127.0.0.1:1291",
        "VITE_DISABLE_SERVICE_WORKER": "true",
        "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
    },
}
EVIDENCE_UPLOAD_NAMES: dict[tuple[str, str], str] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "nyay18-browser-namespace-attestation",
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
    ): "nyay5-profile-boundary-attestation",
    ("wave1-foundation-gate.yml", "frontend-native"): "v34-s11-s26-browser-attestation",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "wave2-tutoring-db-gate-attestation",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "wave3-credential-trust-attestation",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "wave4-private-reporting-attestation",
    ("wave5-calendar-gate.yml", "calendar-postgres"): "wave5-calendar-postgres-attestation",
    ("wave5-calendar-gate.yml", "calendar-real-browser"): "wave5-calendar-real-browser-attestation",
}
WAVE4_FAILURE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload privacy-safe S-86/S-87 failure diagnostic",
    "condition": "${{ failure() }}",
    "producer": "npm run qa:wave4-reporting",
    "with": {
        "name": "wave4-reporting-failure-diagnostic",
        "path": "${{ github.workspace }}/test-results/wave4-browser/results.json",
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
NYAY4_FAILURE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload privacy-safe NYAY-4 failure diagnostic",
    "condition": (
        "${{ failure() && "
        "hashFiles('backend/test-results/nyay4-postgres/summary.json') != '' }}"
    ),
    "producer": "PYTHON=python bash scripts/db_gate.sh",
    "with": {
        "name": "nyay4-postgres-failure-diagnostic",
        "path": (
            "${{ github.workspace }}/backend/test-results/nyay4-postgres/"
            "summary.json"
        ),
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
NYAY22_FAILURE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload privacy-safe NYAY-22 Chromium failure diagnostic",
    "condition": (
        "${{ failure() && "
        "hashFiles('test-results/nyay22-browser/failure.json') != '' }}"
    ),
    "producer": "npm run qa:nyay22:mentor-ceremony",
    "with": {
        "name": "nyay22-mentor-browser-failure-diagnostic",
        "path": (
            "${{ github.workspace }}/test-results/nyay22-browser/failure.json"
        ),
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
NYAY4_QUARANTINE_DIAGNOSTIC_UPLOAD = {
    "name": "Upload detailed quarantine diagnostic",
    "condition": "${{ always() }}",
    "producer": (
        "NYAY4_POSTGRES_GATE=1 python scripts/nyay4_postgres_otp_gate.py "
        "--execute --database-url \"$DATABASE_URL\" "
        "--require-quarantined-assertion "
        "--output test-results/nyay4-ci-flaky/summary.json"
    ),
    "with": {
        "name": "nyay4-cookie-origin-reload-symmetry-diagnostic",
        "path": (
            "${{ github.workspace }}/backend/test-results/"
            "nyay4-ci-flaky/summary.json"
        ),
        "if-no-files-found": "error",
        "retention-days": "14",
        "include-hidden-files": "false",
    },
}
FAILURE_DIAGNOSTIC_UPLOADS = {
    (
        "ci-flaky-nyay4-cookie-reload-symmetry.yml",
        "postgres-16-pgvector-cookie-origin-reload",
    ): NYAY4_QUARANTINE_DIAGNOSTIC_UPLOAD,
    (
        "wave4-private-reporting-gate.yml",
        "private-reporting-postgres-browser",
    ): WAVE4_FAILURE_DIAGNOSTIC_UPLOAD,
    (
        "wave1-foundation-gate.yml",
        "backend-postgres16-gate",
    ): NYAY4_FAILURE_DIAGNOSTIC_UPLOAD,
    (
        "wave3-credential-trust-gate.yml",
        "credential-trust-postgres-browser",
    ): NYAY22_FAILURE_DIAGNOSTIC_UPLOAD,
}
DIRECT_EVIDENCE_UPLOAD_PATHS: dict[tuple[str, str], str] = {
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "$RUNNER_TEMP/nyay18-browser-uploadable",
}
REQUIRED_JOB_RUNS: dict[tuple[str, str], set[str]] = {
    ("nyayone-policy-gate.yml", "policy-contracts"): {
        "python scripts/ci/test_nyay40_failure_digests.py",
        "python scripts/ci/test_sprint4_hardening_red.py",
        "python scripts/ci/test_sprint4_hardening_adversarial.py",
        EXPECTED_NYAY14_POLICY_COMMAND,
        EXPECTED_NYAY14_SECURITY_POLICY_COMMAND,
        EXPECTED_NYAY27_POLICY_COMMAND,
        EXPECTED_NYAY21_POLICY_COMMAND,
        EXPECTED_NYAY21_PATH_TO_GO_POLICY_COMMAND,
        "python scripts/ci/test_nyay21_execution_time_seal.py",
        "python scripts/ci/test_nyay21_execution_adversarial.py",
        "python scripts/ci/test_nyay21_executor_adapters.py",
        "python scripts/ci/test_nyay21_executor_runtime.py",
        EXPECTED_NYAY33_POLICY_COMMAND,
        EXPECTED_NYAY22_POLICY_COMMAND,
        EXPECTED_NYAY11_POLICY_COMMAND,
    },
    ("nyay18-frontend-namespace-gate.yml", "namespace-static-policy"): {
        "python scripts/ci/test_nyay18_namespace_boundary_doc.py",
        "python scripts/ci/test_nyay18_namespace_policy.py",
        (
            "python scripts/ci/check_nyay18_frontend_namespaces.py "
            "--output $RUNNER_TEMP/nyay18-static/summary.json"
        ),
    },
    ("nyay5-profile-boundary-gate.yml", "profile-postgres-production-browser"): {
        "(cd backend && PYTHON=python bash scripts/db_gate.sh)",
        "bash scripts/nyay5_profile_browser_gate.sh $GITHUB_WORKSPACE/test-results/nyay5-browser/results.json",
        "python scripts/ci/evidence_manifest.py --seal $GITHUB_WORKSPACE/test-results/nyay5-browser",
        (
            "python scripts/ci/nyay5_acceptance_attestations.py --browser "
            "$GITHUB_WORKSPACE/test-results/nyay5-browser/results.json "
            "--orchestrator $GITHUB_WORKSPACE/test-results/nyay5-browser/orchestrator-summary.json "
            "--postgres $GITHUB_WORKSPACE/test-results/nyay5-postgres/summary.json "
            "--otp-postgres $GITHUB_WORKSPACE/test-results/nyay4-postgres/summary.json "
            "--manifest-root $GITHUB_WORKSPACE/test-results/nyay5-browser "
            "--output $GITHUB_WORKSPACE/test-results/nyay5-acceptance/attestations.json"
        ),
    },
    ("registration-db-gate.yml", "postgres-16-pgvector"): {
        "PYTHON=python bash scripts/db_gate.sh",
    },
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): {
        "PYTHON=python bash scripts/db_gate.sh",
    },
}
ALLOWED_STEP_CONDITIONS = {
    "${{ always() }}",
    "always()",
    EXPECTED_UPLOAD_IF,
    EXPECTED_NYAY18_UPLOAD_IF,
}
NO_OP_RUN_COMMANDS = {":", "exit 0", "true"}
EXPECTED_JOB_SEMANTIC_SHA256: dict[tuple[str, str], str] = {
    (
        "ci-flaky-nyay4-cookie-reload-symmetry.yml",
        "postgres-16-pgvector-cookie-origin-reload",
    ): "a9165baf7120fea7ea964b847de401092e5caab8d6f2b19fadc7b0555abf586d",
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-static-policy",
    ): "43aeca7cc88ae6e4bf980117236dc3e69ce300e4937e3b9c3e8010e2a1c14e13",
    (
        "nyay18-frontend-namespace-gate.yml",
        "namespace-production-chromium",
    ): "2938507619c53fbaa0f319824c4324acdd0518a82dcbc73f02936f01c5b77d33",
    (
        "nyay18-frontend-namespace-gate.yml",
        "required",
    ): "26eb16eddb5471356ee193d4a0817cdab3466eb0d76e38a9aec7ed26bcb279ef",
    (
        "nyay5-profile-boundary-gate.yml",
        "profile-postgres-production-browser",
    ): "d87c17bf770e64a32ac3be6a1d6e480f104e2777e4f738c464cb05071ec05220",
    (
        "nyay5-profile-boundary-gate.yml",
        "required",
    ): "b54939ff87a54c12aa787cd364ef2700d6062a496fbcb08baf99730f5859e5ef",
    ("nyayone-policy-gate.yml", "policy-contracts"): "2e5b71378103aa514afde1a0e44fa36c17e97fcd276e1b77def3217b172cb11e",
    ("nyayone-policy-gate.yml", "required"): "cb7fdec8df817040ee48f877cd06a82a80b252603c51a9bd1771abcdffbe54e2",
    ("registration-db-gate.yml", "postgres-16-pgvector"): "4a5fe899f88d2cd98ec5108af462f8f9c08e612459538ccf809fc3aa23500b26",
    ("registration-db-gate.yml", "required"): "826db470f5620527b0929811c10b0550f6ce56c37e1c0225957731358e2f4aee",
    ("wave1-foundation-gate.yml", "frontend-native"): "7cbafa269bc3a7c511f332cb626068e53bf185bd7d9528b2f4fac707ce1372d3",
    ("wave1-foundation-gate.yml", "backend-postgres16-gate"): "153e02df5a01f3fecadc318a282b1145fbfb7faba905c24d3f75d202153d8911",
    ("wave1-foundation-gate.yml", "required"): "819f6d6b3187a38058f07e01be6573b315be27a9b296c2239731d33c12d8e67f",
    ("wave2-tutoring-db-gate.yml", "wave2-postgres-16-pgvector"): "449af3381247ff7d91c5b6c7a60ab220ecc63308af4553af6dd22a32bdaab758",
    ("wave2-tutoring-db-gate.yml", "required"): "3e311e18909eee9d1d5b63e2aa231a02296d1d17af0edbf5f3fb3f5609c6fd78",
    ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"): "f4e777be98ee755df10fa7e5613ad896fc67efd1d89572580c87ff29d599ed05",
    ("wave3-credential-trust-gate.yml", "required"): "fb8b82abae6dcda07b3b8ab376d13882184fef23e2e17d7941a52656840e33de",
    ("wave4-private-reporting-gate.yml", "private-reporting-postgres-browser"): "4364a064d6289dc2335601bdef539720e52999165b0051ec2c509dd6ebfdc412",
    ("wave4-private-reporting-gate.yml", "required"): "e7dba929f69d1c9783aecf806fed473f2eeb3d5f8155ed95a3e50f71d058e861",
    ("wave5-calendar-gate.yml", "calendar-postgres"): "3e53e60acd87ec409045c0e7fc1dd0bcc474c4c8a13275545d72e0dfd4de7a27",
    ("wave5-calendar-gate.yml", "calendar-real-browser"): "538128276a071cafcc082999f0b912756b4cd71500552432b49659eedd74f6d4",
    ("wave5-calendar-gate.yml", "required"): "c4c8cefe36440feecc52c6968ae30095e94900cf677dbd9d203d2e8c3d07e3f1",
}


if yaml is not None:
    class _NoDuplicateBaseLoader(yaml.BaseLoader):
        """YAML loader with string scalars and recursive duplicate rejection."""

        pass


    def _construct_unique_mapping(loader, node, deep=False):
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be scalar values",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "duplicate mapping key",
                    key_node.start_mark,
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping


    _NoDuplicateBaseLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _run_reaches_nyay4_transitively(run: str) -> bool:
    """Classify jobs whose backend command loads the sealed NYAY-4 source probe."""

    canonical = _canonical_shell(run)
    calls_database_gate = re.search(
        r"(?:^|[ (;&|])bash (?:backend/)?scripts/db_gate\.sh(?:$|[ );&|])",
        canonical,
    ) is not None
    runs_complete_backend_suite = re.search(
        r"(?:^|[ (;&|])(?:python(?:3)? -m )?pytest -q(?=$|[);&|])",
        canonical,
    ) is not None
    calls_nyay4_gate = re.search(
        r"(?:^|[ (;&|])(?:python(?:3)?|\$PY) "
        r"scripts/nyay4_postgres_otp_gate\.py(?:$|[ );&|])",
        canonical,
    ) is not None
    return calls_database_gate or runs_complete_backend_suite or calls_nyay4_gate


def _effective_working_directory(
    job: dict[str, object], step: dict[str, object]
) -> object:
    if "working-directory" in step:
        return step["working-directory"]
    defaults = _mapping(job.get("defaults")) or {}
    run_defaults = _mapping(defaults.get("run")) or {}
    return run_defaults.get("working-directory")


def _exact_npm_ci_count(run: str) -> int:
    return sum(
        _canonical_shell(line) == "npm ci"
        for line in run.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _nyay4_frontend_dependency_failures(
    path: Path, jobs: dict[str, object]
) -> list[str]:
    """Require Node/Vitest dependencies in every NYAY-4-transitive job.

    GitHub jobs do not share filesystems. A sibling frontend job cannot provide
    ``node_modules`` to a backend job whose complete suite or ``db_gate.sh``
    reaches NYAY-4's frontend source contracts, so provisioning must be exact,
    local to the job, and ordered before the first transitive invocation.
    """

    failures: list[str] = []
    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            continue
        raw_steps = job.get("steps")
        if not isinstance(raw_steps, list):
            continue
        steps = [_mapping(step) for step in raw_steps]
        transitive_indexes = [
            index
            for index, step in enumerate(steps)
            if step is not None
            and isinstance(step.get("run"), str)
            and _run_reaches_nyay4_transitively(str(step["run"]))
        ]
        if not transitive_indexes:
            continue
        first_gate = min(transitive_indexes)

        setup_node = [
            (index, step)
            for index, step in enumerate(steps)
            if step is not None and step.get("uses") == PINNED_SETUP_NODE_ACTION
        ]
        if not (
            len(setup_node) == 1
            and setup_node[0][0] < first_gate
            and setup_node[0][1].get("with") == EXPECTED_NYAY4_SETUP_NODE_WITH
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-4-transitive job must provision "
                "exact pinned Node 22 before its backend gate"
            )

        npm_ci = [
            (index, _exact_npm_ci_count(str(step["run"])))
            for index, step in enumerate(steps)
            if step is not None
            and isinstance(step.get("run"), str)
            and _effective_working_directory(job, step) == "frontend"
            and _exact_npm_ci_count(str(step["run"]))
        ]
        if not (
            sum(count for _, count in npm_ci) == 1
            and len(npm_ci) == 1
            and npm_ci[0][0] < first_gate
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-4-transitive job must run exact "
                "npm ci from frontend before its backend gate"
            )
    return failures


def _nyay19_isolated_postgres_url_is_exact(value: object) -> bool:
    """Match the release guard's static, fail-closed CI target subset."""

    if not isinstance(value, str) or not value.startswith("postgresql+"):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or not parsed.username
        or parsed.password is None
        or parsed.query
        or parsed.fragment
    ):
        return False
    database = parsed.path.removeprefix("/")
    if not database or any(
        marker in database.casefold()
        for marker in NYAY19_FORBIDDEN_DATABASE_MARKERS
    ):
        return False
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", database.casefold())
        if token
    }
    return bool(tokens & NYAY19_ISOLATED_DATABASE_MARKERS)


def _nyay19_workflow_alembic_failures(
    path: Path,
    jobs: dict[str, object],
) -> list[str]:
    """Require explicit isolated authority only on sealed Alembic CI jobs."""

    failures: list[str] = []
    all_caller_markers = {
        marker
        for markers in EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS.values()
        for marker in markers
    }
    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            continue
        job_env = _mapping(job.get("env")) if "env" in job else {}
        if job_env is None:
            job_env = {}
        steps = job.get("steps")
        step_mappings = [
            step
            for step in steps if isinstance(step, dict)
        ] if isinstance(steps, list) else []
        run_text = "\n".join(
            str(step["run"])
            for step in step_mappings
            if isinstance(step.get("run"), str)
        )
        canonical_run = _canonical_shell(run_text)
        key = (path.name, job_id)
        expected_markers = EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS.get(key)
        has_known_caller = any(
            marker in canonical_run for marker in all_caller_markers
        )
        has_direct_alembic = (
            "-m alembic" in canonical_run
            or re.search(
                r"(?:^| )alembic (?:[^ ]+ )*"
                r"(?:upgrade|downgrade|check|current|stamp)(?: |$)",
                canonical_run,
            ) is not None
        )
        step_opt_ins = [
            _mapping(step.get("env")).get(NYAY19_ISOLATED_MIGRATION_ENV)
            for step in step_mappings
            if _mapping(step.get("env")) is not None
            and NYAY19_ISOLATED_MIGRATION_ENV in _mapping(step.get("env"))
        ]

        if expected_markers is None:
            if (
                has_known_caller
                or has_direct_alembic
                or NYAY19_ISOLATED_MIGRATION_ENV in job_env
                or step_opt_ins
            ):
                failures.append(
                    f"{path}: job {job_id} has unclassified NYAY-19 isolated Alembic authority"
                )
            continue

        if job_env.get(NYAY19_ISOLATED_MIGRATION_ENV) != "1":
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic authority must be exactly 1 at job scope"
            )
        if step_opt_ins:
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic authority may not be shadowed at step scope"
            )
        if job_env.get("APP_ENV") not in NYAY19_ISOLATED_APP_ENVS:
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic APP_ENV is not allowlisted"
            )
        if not any(
            isinstance(_mapping(service), dict)
            and isinstance(_mapping(service).get("image"), str)
            and (
                "postgres" in str(_mapping(service)["image"]).casefold()
                or "pgvector" in str(_mapping(service)["image"]).casefold()
            )
            for service in (_mapping(job.get("services")) or {}).values()
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic requires its own PostgreSQL service"
            )
        for marker in expected_markers:
            if marker not in canonical_run:
                failures.append(
                    f"{path}: job {job_id} NYAY-19 isolated Alembic caller is missing: {marker}"
                )

        url_values = [
            value
            for name, value in job_env.items()
            if name.endswith("DATABASE_URL")
        ]
        url_values.extend(
            re.findall(
                r"postgresql(?:\+[A-Za-z0-9_]+)?://[^\s'\"\\]+",
                run_text,
            )
        )
        if not url_values or any(
            not _nyay19_isolated_postgres_url_is_exact(value)
            for value in url_values
        ):
            failures.append(
                f"{path}: job {job_id} NYAY-19 isolated Alembic URLs must use a marker-named database on literal 127.0.0.1"
            )
    return failures


def _structural_workflow_failures(text: str, path: Path) -> list[str]:
    """Validate security-sensitive workflow semantics with a real YAML parser.

    Text checks below intentionally retain canonical formatting and exact shell
    command contracts. This parser is the authority for YAML equivalence:
    quoted keys, inline maps, explicit keys and duplicate last-key-wins forms
    cannot become invisible to the policy oracle.
    """

    if yaml is None:
        return [f"{path}: PyYAML 6.0.3 is required for structural workflow policy"]
    try:
        document = yaml.load(text, Loader=_NoDuplicateBaseLoader)
    except yaml.YAMLError:
        return [f"{path}: workflow YAML is invalid or contains a duplicate mapping key"]
    root = _mapping(document)
    if root is None:
        return [f"{path}: workflow root must be a YAML mapping"]

    failures: list[str] = []
    if "env" in root:
        failures.append(f"{path}: workflow-level env is forbidden")
    if "defaults" in root:
        failures.append(f"{path}: workflow-level defaults are forbidden")
    if root.get("permissions") != {"contents": "read"}:
        failures.append(f"{path}: workflow permissions must be exactly contents: read")

    jobs = _mapping(root.get("jobs"))
    if not jobs:
        return failures + [f"{path}: jobs must be a non-empty mapping"]
    failures.extend(_nyay19_workflow_alembic_failures(path, jobs))
    failures.extend(_nyay4_frontend_dependency_failures(path, jobs))
    expected_job_ids = {
        job_id
        for workflow_name, job_id in EXPECTED_JOB_SEMANTIC_SHA256
        if workflow_name == path.name
    }
    if set(jobs) != expected_job_ids:
        failures.append(f"{path}: job inventory differs from the canonical contract")

    for job_id, raw_job in jobs.items():
        job = _mapping(raw_job)
        if job is None:
            failures.append(f"{path}: job {job_id} must be a mapping")
            continue
        semantic_payload = json.dumps(
            job,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        expected_semantic_digest = EXPECTED_JOB_SEMANTIC_SHA256.get(
            (path.name, job_id)
        )
        if (
            expected_semantic_digest is None
            or hashlib.sha256(semantic_payload).hexdigest()
            != expected_semantic_digest
        ):
            failures.append(
                f"{path}: job {job_id} differs from the canonical semantic contract"
            )
        if "container" in job:
            failures.append(f"{path}: job {job_id} may not use a job container")
        if "uses" in job:
            failures.append(f"{path}: job {job_id} may not call a reusable workflow")
        if "permissions" in job:
            failures.append(f"{path}: job {job_id} may not override token permissions")
        if "continue-on-error" in job:
            failures.append(f"{path}: job {job_id} may not continue on error")
        if job.get("runs-on") != "ubuntu-24.04":
            failures.append(f"{path}: job {job_id} runner must be exactly ubuntu-24.04")
        if job_id == "required":
            if job.get("if") != "${{ always() }}":
                failures.append(
                    f"{path}: required aggregator job condition must be exactly always()"
                )
        elif "if" in job:
            failures.append(f"{path}: producer job {job_id} may not be conditional")

        services = _mapping(job.get("services")) if "services" in job else {}
        if services is None:
            failures.append(f"{path}: job {job_id} services must be a mapping")
            services = {}
        for service_id, raw_service in services.items():
            service = _mapping(raw_service)
            if service is None or service.get("image") not in ALLOWED_SERVICE_IMAGE_REFS:
                failures.append(
                    f"{path}: job {job_id} service {service_id} image reference is not allowlisted"
                )

        expected_defaults = EXPECTED_JOB_DEFAULTS.get((path.name, job_id))
        if job.get("defaults") != expected_defaults and (
            "defaults" in job or expected_defaults is not None
        ):
            failures.append(
                f"{path}: job {job_id} defaults differ from the canonical working directory"
            )

        job_env = _mapping(job.get("env")) if "env" in job else {}
        if job_env is None:
            failures.append(f"{path}: job {job_id} env must be a mapping")
            job_env = {}
        for key in job_env:
            if key.upper() in DANGEROUS_ENV_KEYS:
                failures.append(f"{path}: job {job_id} overrides a protected environment key")
        expected_job_env = EXPECTED_JOB_ENVS.get((path.name, job_id), {})
        if job_env != expected_job_env:
            failures.append(
                f"{path}: job {job_id} environment differs from the canonical target-runtime contract"
            )

        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            failures.append(f"{path}: job {job_id} needs a non-empty steps list")
            continue
        for index, raw_step in enumerate(steps, 1):
            step = _mapping(raw_step)
            if step is None:
                failures.append(f"{path}: job {job_id} step {index} must be a mapping")
                continue
            if ("uses" in step) == ("run" in step):
                failures.append(
                    f"{path}: job {job_id} step {index} needs exactly one of uses or run"
                )
            if "continue-on-error" in step:
                failures.append(
                    f"{path}: job {job_id} step {index} may not continue on error"
                )
            if "shell" in step and step.get("shell") != "bash":
                failures.append(
                    f"{path}: job {job_id} step {index} has a noncanonical shell override"
                )
            condition = step.get("if")
            diagnostic_contract = FAILURE_DIAGNOSTIC_UPLOADS.get(
                (path.name, job_id)
            )
            diagnostic_upload = bool(
                diagnostic_contract is not None
                and step.get("name") == diagnostic_contract["name"]
            )
            diagnostic_condition = (
                diagnostic_contract["condition"]
                if diagnostic_contract is not None
                else None
            )
            if (
                condition is not None
                and condition not in ALLOWED_STEP_CONDITIONS
                and not (diagnostic_upload and condition == diagnostic_condition)
            ):
                failures.append(
                    f"{path}: job {job_id} step {index} has a noncanonical condition"
                )
            step_env = _mapping(step.get("env")) if "env" in step else {}
            if step_env is None:
                failures.append(f"{path}: job {job_id} step {index} env must be a mapping")
                step_env = {}
            for key in step_env:
                if key.upper() in DANGEROUS_ENV_KEYS:
                    failures.append(
                        f"{path}: job {job_id} step {index} overrides a protected environment key"
                    )
            action = step.get("uses")
            if action is not None and action not in ALLOWED_ACTIONS:
                failures.append(
                    f"{path}: job {job_id} step {index} action identity is not allowlisted"
                )
            if action == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262":
                if step.get("with") != {
                    "persist-credentials": "false",
                    "fetch-depth": "0",
                }:
                    failures.append(
                        f"{path}: job {job_id} checkout must use the exact head-safe configuration"
                    )
            if action == "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02":
                if diagnostic_upload:
                    if (
                        condition != diagnostic_condition
                        or step.get("with") != diagnostic_contract["with"]
                    ):
                        failures.append(
                            f"{path}: job {job_id} diagnostic upload configuration is not exact"
                        )
                    continue
                contract = EVIDENCE_CONTRACTS.get(path.name, {}).get(job_id)
                evidence_key = (path.name, job_id)
                expected_name = EVIDENCE_UPLOAD_NAMES.get(evidence_key)
                direct_path = DIRECT_EVIDENCE_UPLOAD_PATHS.get(evidence_key)
                canonical_path = direct_path or (contract[1] if contract else None)
                expected_path = (
                    canonical_path.replace("$RUNNER_TEMP", "${{ runner.temp }}")
                    if canonical_path
                    else None
                )
                if step.get("with") != {
                    "name": expected_name,
                    "path": expected_path,
                    "if-no-files-found": "error",
                    "retention-days": "14",
                    "include-hidden-files": "false",
                }:
                    failures.append(
                        f"{path}: job {job_id} upload configuration is not exact"
                    )

            run = step.get("run")
            if isinstance(run, str) and _canonical_shell(run) in NO_OP_RUN_COMMANDS:
                failures.append(
                    f"{path}: job {job_id} step {index} is an explicit no-op"
                )

        if (
            path.name == "nyay18-frontend-namespace-gate.yml"
            and job_id == "namespace-production-chromium"
        ):
            chain_length = len(EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN)
            actual_chain = tuple(steps[-chain_length:])
            if actual_chain != EXPECTED_NYAY18_BROWSER_EVIDENCE_CHAIN:
                failures.append(
                    f"{path}: NYAY-18 browser evidence chain differs from the exact "
                    "raw-integrity and privacy-safe upload contract"
                )

        required_runs = REQUIRED_JOB_RUNS.get((path.name, job_id), set())
        for required_run in sorted(required_runs):
            matching_steps = [
                step
                for step in steps
                if isinstance(step, dict)
                and isinstance(step.get("run"), str)
                and _canonical_shell(str(step["run"])) == required_run
            ]
            if len(matching_steps) != 1:
                failures.append(
                    f"{path}: job {job_id} must contain the required gate command exactly once: {required_run}"
                )
                continue
            extra_keys = sorted(set(matching_steps[0]) - {"name", "run"})
            if extra_keys:
                failures.append(
                    f"{path}: job {job_id} required gate command has forbidden keys: "
                    + ", ".join(extra_keys)
                )

        exact_steps = {
            name: contract
            for (workflow_name, expected_job_id, name), contract
            in EXPECTED_EXACT_STEPS.items()
            if workflow_name == path.name and expected_job_id == job_id
        }
        for name, contract in exact_steps.items():
            matching_steps = [
                step
                for step in steps
                if isinstance(step, dict) and step.get("name") == name
            ]
            if len(matching_steps) != 1 or matching_steps[0] != contract:
                failures.append(
                    f"{path}: job {job_id} step {name!r} differs from the exact required contract"
                )

        if (
            path.name == "wave3-credential-trust-gate.yml"
            and job_id == "credential-trust-postgres-browser"
        ):
            ordered_names = (
                "NYAY-4 OTP authority Chromium regression",
                "Start NYAY-19 isolated auth lifecycle backend and frontend",
                "NYAY-19 authentication lifecycle Chromium regression",
            )
            name_indexes = {
                name: [
                    index
                    for index, step in enumerate(steps)
                    if isinstance(step, dict) and step.get("name") == name
                ]
                for name in ordered_names
            }
            if any(len(indexes) != 1 for indexes in name_indexes.values()):
                failures.append(
                    f"{path}: NYAY-19 isolated startup and browser gate must each "
                    "appear exactly once after NYAY-4"
                )
            else:
                nyay4_index, startup_index, browser_index = (
                    name_indexes[name][0] for name in ordered_names
                )
                if not (
                    startup_index == nyay4_index + 1
                    and browser_index == startup_index + 1
                ):
                    failures.append(
                        f"{path}: NYAY-19 isolated startup and browser gate must be "
                        "adjacent and immediately follow NYAY-4"
                    )

        if job_id == "required":
            forbidden_required = {
                "container", "continue-on-error", "defaults", "env", "permissions",
                "services", "strategy", "uses",
            }
            present = sorted(forbidden_required & set(job))
            if present:
                failures.append(
                    f"{path}: required aggregator has forbidden job keys: {', '.join(present)}"
                )
            if len(steps) == 1 and isinstance(steps[0], dict):
                allowed_step_keys = {"env", "name", "run"}
                extra = sorted(set(steps[0]) - allowed_step_keys)
                if extra:
                    failures.append(
                        f"{path}: required aggregator step has forbidden keys: {', '.join(extra)}"
                    )
                if steps[0].get("env") != {"RESULTS": "${{ toJSON(needs) }}"}:
                    failures.append(f"{path}: required aggregator env is not exact")

    return failures


def _step_blocks(job_block: str) -> list[str]:
    starts = list(re.finditer(r"^      - (?=\S)", job_block, re.MULTILINE))
    return [
        job_block[match.start() : starts[index + 1].start()]
        if index + 1 < len(starts)
        else job_block[match.start() :]
        for index, match in enumerate(starts)
    ]


def _step_id(step: str) -> str | None:
    match = re.search(r"^        id:\s*([a-zA-Z0-9_-]+)\s*$", step, re.MULTILINE)
    return match.group(1) if match else None


def _run_payload(step: str) -> str | None:
    match = re.search(r"^        run:\s*(.*?)\s*$", step, re.MULTILINE)
    if not match:
        return None
    marker = match.group(1)
    if marker not in {"|", "|-", ">", ">-"}:
        return marker
    lines: list[str] = []
    for line in step[match.end() :].splitlines():
        if not line.strip():
            lines.append("")
            continue
        if not line.startswith("          "):
            break
        lines.append(line[10:])
    separator = "\n" if marker.startswith("|") else " "
    return separator.join(lines).strip()


def _canonical_shell(command: str) -> str:
    normalized = re.sub(
        r"\$\{\{\s*runner\.temp\s*\}\}", "$RUNNER_TEMP", command
    )
    normalized = re.sub(
        r"\$\{\{\s*github\.workspace\s*\}\}", "$GITHUB_WORKSPACE", normalized
    )
    normalized = normalized.replace('"', "").replace("'", "")
    return " ".join(normalized.split())


def check_nyay11_db_gate_contract(path: Path = DB_GATE) -> list[str]:
    """Require the authority stage unconditionally between the retained gates.

    The complete db_gate digest additionally seals the surrounding shell. This
    local adjacency contract rejects conditional wrappers and ignored failures
    independently of that digest, while preserving NYAY-22's exact final tail.
    """
    if not path.is_file() or path.is_symlink():
        return ["NYAY11_DB_GATE_UNAVAILABLE"]
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["NYAY11_DB_GATE_UNREADABLE"]
    bounded = (
        "  --output test-results/nyay19-postgres/summary.json\n"
        + EXPECTED_NYAY11_DB_GATE_BLOCK
        + EXPECTED_NYAY22_DB_GATE_STAGE
    )
    if (
        source.count(EXPECTED_NYAY11_DB_GATE_BLOCK) != 1
        or source.count("scripts/nyay11_postgres_authority_gate.py") != 1
        or source.count(bounded) != 1
        or "set -euo pipefail\n" not in source
    ):
        return ["NYAY11_DB_GATE_NOT_EXACT_UNCONDITIONAL_STAGE"]
    return []


def check_db_gate_contract(path: Path = DB_GATE) -> list[str]:
    """Seal the nested shell gate reached by required registration CI.

    The workflow's semantic digest protects the call *to* db_gate.sh.  This
    companion contract protects the executable reached through that call, so
    leaving the workflow untouched while deleting/bypassing NYAY-16, NYAY-3,
    NYAY-2, NYAY-5, NYAY-17, NYAY-4, NYAY-19, or NYAY-22 cannot produce a
    false green.
    """

    if not path.is_file() or path.is_symlink():
        return [f"{path}: database gate is missing or unsafe"]
    try:
        raw = path.read_bytes()
        source = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path}: database gate cannot be read: {type(exc).__name__}"]

    failures: list[str] = []
    if hashlib.sha256(raw).hexdigest() != EXPECTED_DB_GATE_SHA256:
        failures.append(f"{path}: database gate SHA-256 differs from the sealed contract")

    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    executable = re.sub(r"\\\s*\n", " ", executable)
    canonical = _canonical_shell(executable)
    isolated_pytest = _canonical_shell(EXPECTED_ISOLATED_BACKEND_PYTEST_COMMAND)
    nyay16 = _canonical_shell(EXPECTED_NYAY16_DB_GATE_COMMAND)
    nyay3 = _canonical_shell(EXPECTED_NYAY3_DB_GATE_COMMAND)
    nyay2 = _canonical_shell(EXPECTED_NYAY2_DB_GATE_COMMAND)
    nyay5 = _canonical_shell(EXPECTED_NYAY5_DB_GATE_COMMAND)
    nyay9 = _canonical_shell(EXPECTED_NYAY9_DB_GATE_COMMAND)
    nyay17 = _canonical_shell(EXPECTED_NYAY17_DB_GATE_COMMAND)
    nyay4 = _canonical_shell(EXPECTED_NYAY4_DB_GATE_COMMAND)
    nyay19 = _canonical_shell(EXPECTED_NYAY19_DB_GATE_COMMAND)
    nyay22 = _canonical_shell(EXPECTED_NYAY22_DB_GATE_COMMAND)
    nyay22_promotion = _canonical_shell(
        re.sub(
            r"\\\s*\n",
            " ",
            EXPECTED_NYAY22_DB_GATE_EVIDENCE_PROMOTION,
        )
    )
    if canonical.count(isolated_pytest) != 1:
        failures.append(
            f"{path}: backend pytest must clear deployment-only CORS and mentor "
            "retention environment exactly once"
        )
    if canonical.count(nyay16) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-16 PostgreSQL gate once"
        )
    if canonical.count(nyay3) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-3 PostgreSQL gate once"
        )
    if canonical.count(nyay2) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-2 PostgreSQL gate once"
        )
    if canonical.count(nyay5) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-5 PostgreSQL gate once"
        )
    if canonical.count(nyay9) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-9 PostgreSQL gate once"
        )
    if canonical.count(nyay17) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-17 PostgreSQL gate once"
        )
    if canonical.count(nyay4) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-4 PostgreSQL gate once"
        )
    if canonical.count(nyay19) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-19 PostgreSQL gate once"
        )
    if canonical.count(nyay22) != 1:
        failures.append(
            f"{path}: database gate must invoke the exact NYAY-22 PostgreSQL gate once"
        )
    if canonical.count(nyay22_promotion) != 1:
        failures.append(
            f"{path}: database gate must promote the validated NYAY-22 summary exactly once"
        )
    if (
        nyay5 in canonical
        and nyay9 in canonical
        and canonical.index(nyay9) < canonical.index(nyay5)
    ):
        failures.append(
            f"{path}: NYAY-9 PostgreSQL gate must remain after the inherited NYAY-5 stage"
        )
    wave2 = _canonical_shell('PYTHON="$PY" bash scripts/wave2_db_gate.sh')
    if (
        wave2 not in canonical
        or nyay16 not in canonical
        or canonical.index(nyay16) < canonical.index(wave2)
    ):
        failures.append(
            f"{path}: NYAY-16 PostgreSQL gate must remain after the inherited Wave 2 stage"
        )
    if (
        nyay16 not in canonical
        or nyay3 not in canonical
        or canonical.index(nyay3) < canonical.index(nyay16)
    ):
        failures.append(
            f"{path}: NYAY-3 PostgreSQL gate must remain after the NYAY-16 stage"
        )
    if (
        nyay3 not in canonical
        or nyay2 not in canonical
        or canonical.index(nyay2) < canonical.index(nyay3)
    ):
        failures.append(
            f"{path}: NYAY-2 PostgreSQL gate must remain after the NYAY-3 stage"
        )
    if (
        nyay2 not in canonical
        or nyay5 not in canonical
        or canonical.index(nyay5) < canonical.index(nyay2)
    ):
        failures.append(
            f"{path}: NYAY-5 PostgreSQL gate must remain after the NYAY-2 stage"
        )
    if (
        nyay5 not in canonical
        or nyay17 not in canonical
        or canonical.index(nyay17) < canonical.index(nyay5)
    ):
        failures.append(
            f"{path}: NYAY-17 PostgreSQL gate must remain after the NYAY-5 stage"
        )
    if (
        nyay17 not in canonical
        or nyay4 not in canonical
        or canonical.index(nyay4) < canonical.index(nyay17)
    ):
        failures.append(
            f"{path}: NYAY-4 PostgreSQL gate must remain after the NYAY-17 stage"
        )
    if (
        nyay4 not in canonical
        or nyay19 not in canonical
        or canonical.index(nyay19) < canonical.index(nyay4)
    ):
        failures.append(
            f"{path}: NYAY-19 PostgreSQL gate must remain after the NYAY-4 stage"
        )
    if (
        nyay19 not in canonical
        or nyay22 not in canonical
        or canonical.index(nyay22) < canonical.index(nyay19)
    ):
        failures.append(
            f"{path}: NYAY-22 PostgreSQL gate must remain after the inherited NYAY-19 stage"
        )

    # NYAY-22 is the final mandatory nested stage. Its only successors are the
    # exact mkdir/copy pair that promotes the producer's already validated,
    # closed-world summary into the uploadable Wave-3 evidence root. Requiring
    # this exact tail rejects wrappers such as ``if false``, ``|| true``,
    # ``--help``, redirection, or any later command that could mask a failure.
    if not canonical.endswith(f"{nyay22} {nyay22_promotion}"):
        failures.append(
            f"{path}: exact NYAY-22 PostgreSQL gate and evidence promotion must be the final unconditional stage"
        )
    return failures


def check_nyay22_browser_gate_contract(
    browser_path: Path = NYAY22_BROWSER_GATE,
    contract_path: Path = NYAY22_BROWSER_CONTRACT,
    contract_test_path: Path = NYAY22_BROWSER_CONTRACT_TEST,
    harness_entry_path: Path = NYAY22_BROWSER_HARNESS_ENTRY,
    fixture_path: Path = NYAY22_BROWSER_FIXTURE,
    seed_path: Path = NYAY22_BROWSER_SEED,
    seed_test_path: Path = NYAY22_BROWSER_SEED_TEST,
    package_path: Path = FRONTEND_PACKAGE,
    workflow_path: Path = NYAY22_REQUIRED_WORKFLOW,
) -> list[str]:
    """Seal both NYAY-22 Chromium authority and required-CI reachability."""

    failures: list[str] = []
    pinned_files = (
        (browser_path, EXPECTED_NYAY22_BROWSER_GATE_SHA256, "browser producer"),
        (
            contract_path,
            EXPECTED_NYAY22_BROWSER_CONTRACT_SHA256,
            "browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY22_BROWSER_CONTRACT_TEST_SHA256,
            "browser assertion contract tests",
        ),
        (
            harness_entry_path,
            EXPECTED_NYAY22_BROWSER_HARNESS_ENTRY_SHA256,
            "browser harness entry",
        ),
        (
            fixture_path,
            EXPECTED_NYAY22_BROWSER_FIXTURE_SHA256,
            "browser fixture",
        ),
        (
            seed_path,
            EXPECTED_NYAY22_BROWSER_SEED_SHA256,
            "private live-fixture seed",
        ),
        (
            seed_test_path,
            EXPECTED_NYAY22_BROWSER_SEED_TEST_SHA256,
            "private live-fixture seed tests",
        ),
    )
    for path, expected, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: NYAY-22 {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: NYAY-22 {label} is missing or unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected:
            failures.append(
                f"{path}: NYAY-22 {label} SHA-256 differs from the sealed contract"
            )

    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: NYAY-22 package contract is unreadable")
    else:
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if (
            not isinstance(scripts, dict)
            or scripts.get("qa:nyay22:mentor-ceremony")
            != EXPECTED_NYAY22_BROWSER_PACKAGE_COMMAND
        ):
            failures.append(
                f"{package_path}: NYAY-22 browser package command is not exact"
            )

    try:
        workflow = workflow_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        failures.append(f"{workflow_path}: NYAY-22 required workflow is unreadable")
    else:
        if workflow.count(EXPECTED_NYAY22_LIVE_SEED_STEP) != 1:
            failures.append(
                f"{workflow_path}: NYAY-22 private live-fixture seed must appear exactly once"
            )
        if workflow.count(EXPECTED_NYAY22_BROWSER_STEP) != 1:
            failures.append(
                f"{workflow_path}: NYAY-22 production browser producer must appear exactly once"
            )
        if workflow.count(EXPECTED_NYAY22_FAILURE_UPLOAD_STEP) != 1:
            failures.append(
                f"{workflow_path}: NYAY-22 privacy-safe failure upload must appear exactly once"
            )
        if (
            EXPECTED_NYAY22_LIVE_SEED_STEP + EXPECTED_NYAY22_BROWSER_STEP
            not in workflow
        ):
            failures.append(
                f"{workflow_path}: NYAY-22 private live-fixture seed must immediately precede its producer"
            )
        if (
            EXPECTED_NYAY22_BROWSER_STEP + EXPECTED_NYAY22_FAILURE_UPLOAD_STEP
            not in workflow
        ):
            failures.append(
                f"{workflow_path}: NYAY-22 failure upload must immediately follow its producer"
            )

    try:
        browser_source = browser_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        browser_source = ""
    for marker in (
        "NYAY22_BROWSER_PRODUCTION_BUILD",
        "NYAY22_LIVE_API_BASE_URL",
        "NYAY22_LIVE_FIXTURE_PATH",
        "NYAY22_BROWSER_FAILURE_PATH",
        "buildVite",
        "previewVite",
        "live-backend-positive-lifecycle",
        "canonicalNyay22BrowserFailureCode",
    ):
        if marker not in browser_source:
            failures.append(
                f"{browser_path}: NYAY-22 production/live/fail-safe marker missing: {marker}"
            )
    if "createViteServer" in browser_source:
        failures.append(
            f"{browser_path}: NYAY-22 required producer may not use the Vite development server"
        )

    try:
        harness_source = harness_entry_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        harness_source = ""
    if (
        "HARNESS_FAILURE_CODES" not in harness_source
        or "safeError" not in harness_source
        or "verifyMentorIdentity" not in harness_source
    ):
        failures.append(
            f"{harness_entry_path}: NYAY-22 browser harness canonical failure-code mapping is missing"
        )
    if "^[A-Za-z0-9_:-]" in harness_source:
        failures.append(
            f"{harness_entry_path}: NYAY-22 browser harness may not echo regex-safe arbitrary errors"
        )
    try:
        seed_source = seed_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        seed_source = ""
    for marker in (
        'OPT_IN_ENV = "NYAY22_BROWSER_FIXTURE_SEED"',
        'os.environ.get(OPT_IN_ENV) != "1"',
        'os.environ.get("RUNNER_TEMP", "").strip()',
        "os.O_EXCL",
        "stat.S_IRUSR | stat.S_IWUSR",
        "NYAY22_BROWSER_FIXTURE_DATABASE_NOT_ISOLATED",
    ):
        if marker not in seed_source:
            failures.append(
                f"{seed_path}: NYAY-22 private live-fixture safety marker missing"
            )
    for marker in (
        "readPrivateLiveFixture",
        "await rm(target, { force: true })",
        "sameOriginProxy: true",
        "liveLifecycle.required === true && liveLifecycle.bound === true",
    ):
        if marker not in browser_source:
            failures.append(
                f"{browser_path}: NYAY-22 live lifecycle fail-closed marker missing"
            )
    return failures


def check_nyay22_postgres_gate_contract(
    producer_path: Path = NYAY22_POSTGRES_GATE,
    contract_path: Path = NYAY22_POSTGRES_CONTRACT,
) -> list[str]:
    """Seal the executable native NYAY-22 producer and its closed-world contract.

    ``db_gate.sh`` reachability alone is not authority: an edited producer could
    retain the same command while silently dropping a race or migration oracle.
    This check binds both executable bytes and the independently versioned
    inventory, then parses the producer constants so head/revision/count drift
    receives an actionable fail-closed diagnostic in addition to the SHA seal.
    """

    failures: list[str] = []
    raw_by_label: dict[str, bytes] = {}
    for path, expected, label in (
        (
            producer_path,
            EXPECTED_NYAY22_POSTGRES_GATE_SHA256,
            "native PostgreSQL producer",
        ),
        (
            contract_path,
            EXPECTED_NYAY22_POSTGRES_CONTRACT_SHA256,
            "native PostgreSQL contract",
        ),
    ):
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: NYAY-22 {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: NYAY-22 {label} is unreadable")
            continue
        raw_by_label[label] = raw
        if hashlib.sha256(raw).hexdigest() != expected:
            failures.append(
                f"{path}: NYAY-22 {label} SHA-256 differs from the sealed contract"
            )

    expected_contract = {
        "schemaVersion": EXPECTED_NYAY22_POSTGRES_SCHEMA,
        "producer": "backend/scripts/nyay22_postgres_mentor_gate.py",
        "optInEnvironment": "NYAY22_POSTGRES_GATE",
        "oracleInventory": list(EXPECTED_NYAY22_POSTGRES_ORACLES),
        "oracleCount": len(EXPECTED_NYAY22_POSTGRES_ORACLES),
        "applicationHead": EXPECTED_NYAY22_APPLICATION_HEAD,
        "previousRevision": EXPECTED_NYAY22_PREVIOUS_REVISION,
    }

    contract: object = None
    contract_raw = raw_by_label.get("native PostgreSQL contract")
    if contract_raw is not None:
        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        try:
            contract = json.loads(
                contract_raw.decode("utf-8"),
                object_pairs_hook=reject_duplicate_pairs,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError):
            failures.append(
                f"{contract_path}: NYAY-22 native PostgreSQL contract is invalid"
            )

    if not isinstance(contract, dict):
        if contract_raw is not None:
            failures.append(
                f"{contract_path}: NYAY-22 native PostgreSQL contract must be an object"
            )
    else:
        if set(contract) != set(expected_contract):
            failures.append(
                f"{contract_path}: NYAY-22 native PostgreSQL contract violates the closed-world field inventory"
            )
        field_diagnostics = {
            "schemaVersion": "schema version",
            "producer": "producer path",
            "optInEnvironment": "opt-in environment",
            "oracleInventory": "oracle inventory",
            "oracleCount": "oracle count",
            "applicationHead": "application head",
            "previousRevision": "previous revision",
        }
        for field, diagnostic in field_diagnostics.items():
            if contract.get(field) != expected_contract[field]:
                failures.append(
                    f"{contract_path}: NYAY-22 native PostgreSQL {diagnostic} differs from the sealed contract"
                )

    producer_raw = raw_by_label.get("native PostgreSQL producer")
    if producer_raw is not None:
        try:
            producer_source = producer_raw.decode("utf-8")
            module = ast.parse(producer_source, filename=str(producer_path))
        except (UnicodeError, SyntaxError):
            failures.append(
                f"{producer_path}: NYAY-22 native PostgreSQL producer is not valid Python"
            )
        else:
            assignments: dict[str, object] = {}
            for node in module.body:
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    try:
                        assignments[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    try:
                        assignments[node.target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        continue

            producer_expectations = {
                "SCHEMA_VERSION": (
                    EXPECTED_NYAY22_POSTGRES_SCHEMA,
                    "schema version",
                ),
                "OPT_IN_ENV": ("NYAY22_POSTGRES_GATE", "opt-in environment"),
                "ORACLE_IDS": (
                    EXPECTED_NYAY22_POSTGRES_ORACLES,
                    "oracle inventory",
                ),
                "APPLICATION_HEAD": (
                    EXPECTED_NYAY22_APPLICATION_HEAD,
                    "application head",
                ),
                "PREVIOUS_REVISION": (
                    EXPECTED_NYAY22_PREVIOUS_REVISION,
                    "previous revision",
                ),
            }
            for name, (expected, diagnostic) in producer_expectations.items():
                if assignments.get(name) != expected:
                    failures.append(
                        f"{producer_path}: NYAY-22 producer {diagnostic} differs from the sealed contract"
                    )
            for cli_marker in ("--database-url", "--output", "--contract-check"):
                if producer_source.count(f'"{cli_marker}"') != 1:
                    failures.append(
                        f"{producer_path}: NYAY-22 producer CLI marker is not exact: {cli_marker}"
                    )

            functions = {
                node.name: node
                for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required_functions = {
                "_migration_downgrade_toctou_oracle",
                "_migration_oracle",
                "_postgres_bounds_oracle",
                "_idempotency_oracles",
                "_provider_subject_unique_race",
                "_exchange_race",
                "_recovery_active_set_snapshot_oracle",
                "_expired_mentor_owner_login_race_oracle",
                "_expired_owner_cookie_mentor_race_oracle",
                "_owner_exclusion",
                "_session_read_only_idle_boundary_oracle",
                "_rotate_end_race",
                "_deletion_historical_subject_actor_isolation_oracle",
                "_deletion_race",
                "_restriction_race",
                "_retention_advisory_oracle",
                "_retention_live_expiry_same_run_proof",
                "_retention_held_node_atomicity_proof",
                "_retention_orphan_erasure_proof",
                "_nyay19_subject_erasure_authority_oracle",
                "_retention_atomic_oracle",
                "_retention_oversize_oracle",
                "_privacy_oracle",
                "_validate_report",
                "run",
            }
            missing_functions = sorted(required_functions - set(functions))
            if missing_functions:
                failures.append(
                    f"{producer_path}: NYAY-22 producer semantic oracle functions are missing"
                )

            def direct_calls(function_name: str) -> list[str]:
                function = functions.get(function_name)
                if function is None:
                    return []
                names: list[str] = []
                for call in (
                    node for node in ast.walk(function) if isinstance(node, ast.Call)
                ):
                    if isinstance(call.func, ast.Name):
                        names.append(call.func.id)
                    elif isinstance(call.func, ast.Attribute):
                        names.append(call.func.attr)
                return names

            run_call_counts = {
                "_migration_oracle": 1,
                "_retention_advisory_oracle": 1,
                "_retention_atomic_oracle": 1,
                "_retention_oversize_oracle": 1,
                "_postgres_bounds_oracle": 1,
                "_idempotency_oracles": 1,
                "_provider_subject_unique_race": 1,
                "_exchange_race": 1,
                "_owner_exclusion": 1,
                "_rotate_end_race": 2,
                "_deletion_race": 2,
                "_restriction_race": 2,
                "_privacy_oracle": 1,
                "_validate_report": 1,
            }
            run_calls = direct_calls("run")
            if any(
                run_calls.count(name) != expected
                for name, expected in run_call_counts.items()
            ):
                failures.append(
                    f"{producer_path}: NYAY-22 producer run orchestration violates the sealed semantic inventory"
                )

            migration_calls = direct_calls("_migration_oracle")
            if migration_calls.count("_migration_downgrade_toctou_oracle") != 1:
                failures.append(
                    f"{producer_path}: NYAY-22 migration subproof orchestration violates the sealed semantic inventory"
                )

            atomic_calls = direct_calls("_retention_atomic_oracle")
            if (
                atomic_calls.count("_retention_live_expiry_same_run_proof") != 1
                or atomic_calls.count("_retention_held_node_atomicity_proof") != 1
                or atomic_calls.count("_retention_orphan_erasure_proof") != 1
                or atomic_calls.count(
                    "_nyay19_subject_erasure_authority_oracle"
                )
                != 1
            ):
                failures.append(
                    f"{producer_path}: NYAY-22 retention subproof orchestration violates the sealed semantic inventory"
                )

            deletion_calls = direct_calls("_deletion_race")
            if (
                deletion_calls.count(
                    "_deletion_historical_subject_actor_isolation_oracle"
                )
                != 1
            ):
                failures.append(
                    f"{producer_path}: NYAY-22 deletion actor-isolation subproof orchestration violates the sealed semantic inventory"
                )

            rotate_calls = direct_calls("_rotate_end_race")
            if rotate_calls.count("_session_read_only_idle_boundary_oracle") != 1:
                failures.append(
                    f"{producer_path}: NYAY-22 session-read subproof orchestration violates the sealed semantic inventory"
                )

            owner_exclusion_calls = direct_calls("_owner_exclusion")
            if (
                owner_exclusion_calls.count(
                    "_recovery_active_set_snapshot_oracle"
                )
                != 1
                or owner_exclusion_calls.count(
                    "_expired_mentor_owner_login_race_oracle"
                )
                != 1
                or owner_exclusion_calls.count(
                    "_expired_owner_cookie_mentor_race_oracle"
                )
                != 1
            ):
                failures.append(
                    f"{producer_path}: NYAY-22 owner/class-exclusion subproof orchestration violates the sealed semantic inventory"
                )

            semantic_markers = {
                "_migration_downgrade_toctou_oracle": (
                    "ACCESS EXCLUSIVE",
                    "pg_stat_activity",
                    'wait_row[0] == "Lock"',
                    "AccessExclusiveLock",
                    "NOT l.granted",
                    "downgrade accepted a concurrent durable row",
                    "all mentor tables were not preserved",
                    "fixture_count != 1",
                ),
                "_migration_oracle": (
                    '"upgrade", PREVIOUS_REVISION',
                    '"upgrade", APPLICATION_HEAD',
                    '"downgrade", PREVIOUS_REVISION',
                    '"mentor_retention_blocked_graphs"',
                ),
                "_postgres_bounds_oracle": (
                    'text("SHOW lock_timeout")',
                    'text("SHOW statement_timeout")',
                    '"CONCURRENT_STATE_CHANGED"',
                ),
                "_idempotency_oracles": (
                    "threading.Barrier(2)",
                    '"IDEMPOTENCY_CONFLICT"',
                    "after_ceremonies != 1",
                ),
                "_provider_subject_unique_race": (
                    "threading.Barrier(2)",
                    '"23505"',
                    '"40P01"',
                ),
                "_deletion_race": (
                    'for order in ("action_first", "revoke_first")',
                    "threading.Barrier(2)",
                    "_assert_deleted_race_terminal",
                ),
                "_deletion_historical_subject_actor_isolation_oracle": (
                    "historical provider-subject actor-isolation",
                    "snapshot_b() != before_b",
                    "unrelated actor graph changed during authority deletion",
                    "deleted actor retained live authority",
                    'b_verified.status_code != 200',
                ),
                "_session_read_only_idle_boundary_oracle": (
                    "session GET changed last_seen_at",
                    "after_read.last_seen_at != original_last_seen",
                    "original idle boundary did not expire authority",
                    'expired_result != (410, "SESSION_EXPIRED")',
                    "expired_last_seen != idle_boundary",
                ),
                "_recovery_active_set_snapshot_oracle": (
                    '"mandatoryRevocationSessionIds"',
                    'denied != (409, "CONCURRENT_STATE_CHANGED")',
                    "after != before",
                    "recovery active-set mismatch mutated authority",
                    'purpose_code="legal_education"',
                ),
                "_expired_mentor_owner_login_race_oracle": (
                    'for operation in ("rotate", "revoke", "logout")',
                    'for order in ("owner_first", "mentor_first")',
                    'text("SHOW lock_timeout")',
                    'text("SHOW statement_timeout")',
                    '"40P01"',
                    '(410, "SESSION_EXPIRED")',
                    '(410, "AUTHORITY_TERMINAL")',
                    "owner/mentor race retained incompatible session classes",
                    "expired-cookie race changed unrelated authority",
                ),
                "_expired_owner_cookie_mentor_race_oracle": (
                    'for operation in ("read", "rotate")',
                    'for order in ("owner_first", "mentor_first")',
                    'text("SHOW lock_timeout")',
                    'text("SHOW statement_timeout")',
                    '"40P01"',
                    "expired owner boundary was not materialized exactly",
                    "owner-cookie race retained incompatible session classes",
                    "owner-cookie race changed unrelated authority",
                ),
                "_restriction_race": (
                    ".with_for_update()",
                    '"AUTHORIZATION_DENIED"',
                    "active != 1 or rows != 1",
                ),
                "_retention_atomic_oracle": (
                    'calls == 7',
                    "_retention_snapshot(factory, context) != before",
                    'counts.get("severed_graphs") != 1',
                    "context[\"old_digests\"] & set(new_digests)",
                    "len(new_digests) != len(set(new_digests))",
                ),
                "_retention_live_expiry_same_run_proof": (
                    'counts.get("materialized_expirations", 0) < 1',
                    'counts.get("severed_graphs") != 1',
                    "_retention_graph_is_fully_severed(factory, context)",
                    '== "owner-create-mentor-prerequisites"',
                    'owner_records[0].state != "erased"',
                ),
                "_retention_held_node_atomicity_proof": (
                    "pg_stat_activity",
                    'wait_event_type == "Lock"',
                    '"40P01"',
                    "_retention_snapshot(factory, context)",
                    "_retention_graph_is_fully_severed(factory, context)",
                    "after == before",
                ),
                "_retention_orphan_erasure_proof": (
                    'counts.get("severed_graphs") != 2',
                    'counts.get("bootstraps") != 2',
                    "residual_joins != 0",
                    "old_digests & new_digests",
                    "unrelated_preserved",
                ),
                "_nyay19_subject_erasure_authority_oracle": (
                    'for mode in ("anonymise", "delete")',
                    'for operation in ("rotate", "read", "exchange")',
                    "threading.Barrier(2)",
                    'text("SET LOCAL lock_timeout = \'5s\'")',
                    'text("SET LOCAL statement_timeout = \'15s\'")',
                    '"40P01"',
                    "NYAY-19 subject erasure left mentor authority",
                    "unrelated subject changed during NYAY-19 erasure",
                ),
                "_retention_oversize_oracle": (
                    "oversize_sessions=256",
                    'first.get("materialized_expirations", 0) != 0',
                    '"GRAPH_EXCEEDS_HARD_CAP"',
                    "occurrence != 2",
                    "_retention_snapshot(factory, context) != before",
                ),
                "_privacy_oracle": (
                    "known_secrets",
                    "audit_count",
                    "link_count",
                ),
                "_validate_report": (
                    "set(report) != expected_report_fields",
                    'set(row) != {"id", "status", "assertions"}',
                    'type(row.get("assertions")) is not int',
                    'row.get("assertions", 0) <= 0',
                ),
            }
            for function_name, markers in semantic_markers.items():
                function = functions.get(function_name)
                segment = (
                    ast.get_source_segment(producer_source, function)
                    if function is not None
                    else ""
                ) or ""
                if any(marker not in segment for marker in markers):
                    failures.append(
                        f"{producer_path}: NYAY-22 producer {function_name} semantic contract differs from the seal"
                    )
    return failures


def check_nyay22_schema_artifact_contract(
    migration_path: Path = NYAY22_SCHEMA_MIGRATION,
    model_path: Path = NYAY22_MENTOR_AUTH_MODEL,
    dispatch_test_path: Path = NYAY22_MIGRATION_DISPATCH_TEST,
) -> list[str]:
    """Bind the NYAY-22 DDL, ORM metadata, and closed-world index oracle.

    The three artifacts form one security contract.  Sealing only the runtime
    producer would allow a coordinated migration/model/test edit to weaken the
    foreign-key index inventory while leaving the native command reachable.
    """

    failures: list[str] = []
    artifacts = (
        (
            migration_path,
            EXPECTED_NYAY22_SCHEMA_MIGRATION_SHA256,
            "mentor ceremony migration",
        ),
        (
            model_path,
            EXPECTED_NYAY22_MENTOR_AUTH_MODEL_SHA256,
            "mentor auth model",
        ),
        (
            dispatch_test_path,
            EXPECTED_NYAY22_MIGRATION_DISPATCH_TEST_SHA256,
            "migration dispatch contract test",
        ),
    )
    for path, expected, label in artifacts:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: NYAY-22 {label} is missing or unsafe")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append(f"{path}: NYAY-22 {label} is unreadable")
            continue
        if actual != expected:
            failures.append(
                f"{path}: NYAY-22 {label} SHA-256 differs from the sealed contract"
            )
    return failures


def check_nyay22_nyay19_erasure_integration_contract(
    test_path: Path = NYAY22_NYAY19_ERASURE_TEST,
) -> list[str]:
    """Seal the NYAY-19 registration/mentor erasure integration proofs."""

    if not test_path.is_file() or test_path.is_symlink():
        return [f"{test_path}: NYAY-22/NYAY-19 erasure integration is missing or unsafe"]
    try:
        raw = test_path.read_bytes()
        source = raw.decode("utf-8")
        module = ast.parse(source, filename=str(test_path))
    except (OSError, UnicodeError, SyntaxError):
        return [f"{test_path}: NYAY-22/NYAY-19 erasure integration is unreadable"]

    failures: list[str] = []
    if hashlib.sha256(raw).hexdigest() != EXPECTED_NYAY22_NYAY19_ERASURE_TEST_SHA256:
        failures.append(
            f"{test_path}: NYAY-22/NYAY-19 erasure integration SHA-256 differs from the sealed contract"
        )
    expected_tests = {
        "test_privacy_delete_over_cap_does_not_consume_recovery_proof",
        "test_terminal_beyond_cutoff_graph_severs_before_registration_anonymise",
        "test_mid_severance_failure_rolls_back_graph_and_registration",
        "test_live_or_young_graph_and_registration_are_both_deferred_bit_identically",
        "test_global_multi_domain_oversize_blocks_without_partial_mutation",
        "test_elapsed_live_oversize_retention_blocks_before_materialization",
    }
    discovered = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    if discovered != expected_tests:
        failures.append(
            f"{test_path}: NYAY-22/NYAY-19 erasure test inventory differs from the sealed contract"
        )
    for marker in (
        "prepare_subject_mentor_registration_erasure",
        "retention.anonymise_registration(db, registration)",
        "retention.delete_registration",
        "_retention_snapshot(factory, context) == graph_before",
        'counts["materialized_expirations"] == 0',
        'counts["blocked_graphs"] == 1',
        '"GRAPH_EXCEEDS_HARD_CAP"',
        '"nyay19_retention_review"',
    ):
        if marker not in source:
            failures.append(
                f"{test_path}: NYAY-22/NYAY-19 erasure semantic contract differs from the seal"
            )
            break
    return failures


def check_nyay4_browser_gate_contract(
    browser_path: Path = NYAY4_BROWSER_GATE,
    contract_path: Path = NYAY4_BROWSER_CONTRACT,
    package_path: Path = FRONTEND_PACKAGE,
    contract_test_path: Path = NYAY4_BROWSER_CONTRACT_TEST,
) -> list[str]:
    """Pin the executable NYAY-4 browser oracle behind the required CI step."""

    failures: list[str] = []
    pinned_files = (
        (
            browser_path,
            EXPECTED_NYAY4_BROWSER_GATE_SHA256,
            "NYAY-4 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY4_BROWSER_CONTRACT_SHA256,
            "NYAY-4 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY4_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-4 browser assertion contract tests",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is missing or unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    gate_name = "qa:nyay4:otp-negative"
    if scripts.get(gate_name) != EXPECTED_NYAY4_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-4 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-4 browser package command may not have an npm lifecycle wrapper"
            )
    return failures


def check_nyay19_browser_gate_contract(
    browser_path: Path = NYAY19_BROWSER_GATE,
    contract_path: Path = NYAY19_BROWSER_CONTRACT,
    package_path: Path = FRONTEND_PACKAGE,
    contract_test_path: Path = NYAY19_BROWSER_CONTRACT_TEST,
) -> list[str]:
    """Pin the executable NYAY-19 browser oracle behind the required CI step."""

    failures: list[str] = []
    pinned_files = (
        (
            browser_path,
            EXPECTED_NYAY19_BROWSER_GATE_SHA256,
            "NYAY-19 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY19_BROWSER_CONTRACT_SHA256,
            "NYAY-19 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY19_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-19 browser assertion contract tests",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    gate_name = "qa:nyay19:auth-lifecycle"
    if scripts.get(gate_name) != EXPECTED_NYAY19_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-19 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-19 browser package command may not have an npm lifecycle wrapper"
            )
    return failures


def check_nyay5_gate_contract(
    orchestrator_path: Path = NYAY5_BROWSER_ORCHESTRATOR,
    browser_path: Path = NYAY5_BROWSER_GATE,
    contract_path: Path = NYAY5_BROWSER_CONTRACT,
    contract_test_path: Path = NYAY5_BROWSER_CONTRACT_TEST,
    control_path: Path = NYAY5_BROWSER_CONTROL,
    postgres_path: Path = NYAY5_POSTGRES_GATE,
    aggregate_path: Path = NYAY5_ACCEPTANCE_AGGREGATE,
    aggregate_test_path: Path = NYAY5_ACCEPTANCE_AGGREGATE_TEST,
    attestation_path: Path = NYAY5_ACCEPTANCE_ATTESTATION_PRODUCER,
    attestation_test_path: Path = NYAY5_ACCEPTANCE_ATTESTATION_TEST,
    package_path: Path = FRONTEND_PACKAGE,
) -> list[str]:
    """Seal the complete executable NYAY-5 producer and aggregate chain."""

    failures: list[str] = []
    pinned_files = (
        (
            orchestrator_path,
            EXPECTED_NYAY5_BROWSER_ORCHESTRATOR_SHA256,
            "NYAY-5 browser orchestrator",
        ),
        (
            browser_path,
            EXPECTED_NYAY5_BROWSER_GATE_SHA256,
            "NYAY-5 browser gate",
        ),
        (
            contract_path,
            EXPECTED_NYAY5_BROWSER_CONTRACT_SHA256,
            "NYAY-5 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY5_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-5 browser assertion contract tests",
        ),
        (
            control_path,
            EXPECTED_NYAY5_BROWSER_CONTROL_SHA256,
            "NYAY-5 scratch-database control",
        ),
        (
            postgres_path,
            EXPECTED_NYAY5_POSTGRES_GATE_SHA256,
            "NYAY-5 PostgreSQL gate",
        ),
        (
            aggregate_path,
            EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_SHA256,
            "NYAY-5 acceptance aggregate",
        ),
        (
            aggregate_test_path,
            EXPECTED_NYAY5_ACCEPTANCE_AGGREGATE_TEST_SHA256,
            "NYAY-5 acceptance aggregate tests",
        ),
        (
            attestation_path,
            EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_SHA256,
            "NYAY-5 acceptance attestation producer",
        ),
        (
            attestation_test_path,
            EXPECTED_NYAY5_ACCEPTANCE_ATTESTATION_TEST_SHA256,
            "NYAY-5 acceptance attestation producer tests",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    commands = {
        "qa:nyay5:profile-boundary": EXPECTED_NYAY5_BROWSER_PACKAGE_COMMAND,
        "qa:nyay5:acceptance": EXPECTED_NYAY5_ACCEPTANCE_PACKAGE_COMMAND,
    }
    for gate_name, expected_command in commands.items():
        if scripts.get(gate_name) != expected_command:
            failures.append(
                f"{package_path}: NYAY-5 {gate_name} package command differs "
                "from the exact contract"
            )
        for hook in (f"pre{gate_name}", f"post{gate_name}"):
            if hook in scripts:
                failures.append(
                    f"{package_path}: NYAY-5 package command may not have an "
                    "npm lifecycle wrapper"
                )
    return failures


def check_nyay18_static_gate_contract(
    detector_path: Path = NYAY18_NAMESPACE_GATE,
    test_path: Path = NYAY18_NAMESPACE_GATE_TEST,
    contract_path: Path = NYAY18_NAMESPACE_CONTRACT,
    document_path: Path = NYAY18_NAMESPACE_BOUNDARY_DOCUMENT,
    document_test_path: Path = NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST,
) -> list[str]:
    """Seal the NYAY-18 detector, planted mutants and compatibility inventory."""

    failures: list[str] = []
    pinned_files = (
        (
            detector_path,
            EXPECTED_NYAY18_NAMESPACE_GATE_SHA256,
            "NYAY-18 detector SHA-256",
        ),
        (
            test_path,
            EXPECTED_NYAY18_NAMESPACE_GATE_TEST_SHA256,
            "NYAY-18 detector tests SHA-256",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_NAMESPACE_CONTRACT_SHA256,
            "NYAY-18 namespace contract SHA-256",
        ),
        (
            document_path,
            EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_SHA256,
            "NYAY-18 boundary document SHA-256",
        ),
        (
            document_test_path,
            EXPECTED_NYAY18_NAMESPACE_BOUNDARY_DOCUMENT_TEST_SHA256,
            "NYAY-18 boundary document tests SHA-256",
        ),
    )
    for path, expected, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} source is missing or unsafe")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append(f"{path}: {label} source is unreadable")
            continue
        if actual != expected:
            failures.append(f"{path}: {label} differs from the sealed contract")

    if contract_path.is_file() and not contract_path.is_symlink():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failures.append(f"{contract_path}: NYAY-18 namespace contract is unreadable")
        else:
            expected_keys = {
                "schema_version",
                "source_inventory_sha256",
                "metadata",
                "required_runtime_namespaces",
                "compatibility_sources",
            }
            if (
                not isinstance(contract, dict)
                or set(contract) != expected_keys
                or contract.get("schema_version") != 1
                or not isinstance(contract.get("source_inventory_sha256"), str)
                or re.fullmatch(
                    r"[0-9a-f]{64}", str(contract.get("source_inventory_sha256"))
                )
                is None
            ):
                failures.append(
                    f"{contract_path}: NYAY-18 namespace contract schema is not exact"
                )
    return failures


def check_nyay14_evidence_gate_contract(
    overrides: dict[str, Path] | None = None,
) -> list[str]:
    """Seal the NYAY-14 validator, oracle, fixture, contract and templates."""

    failures: list[str] = []
    selected = dict(NYAY14_EVIDENCE_FILES)
    if overrides:
        unknown = set(overrides) - set(selected)
        if unknown:
            failures.append(
                "NYAY-14 evidence contract received unknown source overrides: "
                f"{sorted(unknown)}"
            )
        selected.update({key: value for key, value in overrides.items() if key in selected})

    for label, path in selected.items():
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: NYAY-14 {label} source is missing or unsafe")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append(f"{path}: NYAY-14 {label} source is unreadable")
            continue
        if actual != EXPECTED_NYAY14_EVIDENCE_SHA256[label]:
            failures.append(
                f"{path}: NYAY-14 {label} SHA-256 differs from the sealed contract"
            )

    contract_path = selected["contract"]
    fixture_path = selected["seeded_fixture"]
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{contract_path}: NYAY-14 evidence contract is unreadable")
    else:
        if (
            not isinstance(contract, dict)
            or contract.get("schemaVersion") != "nyay14-evidence/v2"
            or contract.get("legacySchemaVersion") != "nyay14-evidence/v1"
            or contract.get("supportedSchemaVersions")
            != ["nyay14-evidence/v1", "nyay14-evidence/v2"]
            or contract.get("defaultAuthoritativeSchemaVersion")
            != "nyay14-evidence/v2"
            or contract.get("classifications")
            != ["PASS", "FAIL", "BLOCKED", "HEAD_CHANGED", "handoff-only"]
            or contract.get("classificationPrecedence")
            != ["HEAD_CHANGED", "FAIL", "BLOCKED", "handoff-only", "PASS"]
            or contract.get("rawLogCategories")
            != [
                "backend",
                "postgresql-migration",
                "postgresql-concurrency",
                "frontend-native",
                "chromium",
            ]
            or not isinstance(contract.get("combinedContactSheet"), dict)
            or contract["combinedContactSheet"].get("policyVersion")
            != "nyay27-contact-sheet-contract/v1"
            or contract["combinedContactSheet"].get("requiredForSchemaVersion")
            != "nyay14-evidence/v2"
            or contract["combinedContactSheet"].get("panelInventoryAuthority")
            != "external"
            or contract["combinedContactSheet"].get("panelSourcesMustBeManifested")
            is not True
            or contract["combinedContactSheet"].get("pngChunkAllowlist")
            != ["IHDR", "IDAT", "IEND"]
            or contract["combinedContactSheet"].get("pngMetadataForbidden")
            is not True
            or contract["combinedContactSheet"].get("sidecarContentBindings")
            != [
                "sheetSha256",
                "sourceArchiveSha256",
                "reviewedHead",
                "panelCount",
                "panelRoles",
            ]
            or contract["combinedContactSheet"].get(
                "privacyScannerVersionRequired"
            )
            is not True
            or contract["combinedContactSheet"].get("repositoryPrivacyScannerRequired")
            is not True
            or not isinstance(contract.get("downgradeResistance"), dict)
            or contract["downgradeResistance"].get("packageSchemaIsAuthority")
            is not False
            or contract["downgradeResistance"].get("packageTimestampIsAuthority")
            is not False
            or contract["downgradeResistance"].get("cliDefault")
            != "nyay14-evidence/v2"
            or contract["downgradeResistance"].get(
                "historicalV1RequiresExactExternalPackageSha256"
            )
            is not True
            or contract["downgradeResistance"].get(
                "admissibleHistoricalV1PackageSha256"
            )
            != [
                "a822ccace60c2c067553bff9c33866a329a811d048d846c9c46317c73bda357f"
            ]
        ):
            failures.append(f"{contract_path}: NYAY-14 evidence contract schema is not exact")
        historical = (
            contract.get("downgradeResistance", {}).get(
                "historicalRecordsPreservedByExactSeal"
            )
            if isinstance(contract, dict)
            else None
        )
        if (
            not isinstance(historical, list)
            or [row.get("ticket") for row in historical if isinstance(row, dict)]
            != ["NYAY-7", "NYAY-9", "NYAY-14", "NYAY-21", "NYAY-28", "NYAY-29"]
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("recordKind"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(row.get("sealSha256")))
                is None
                for row in historical or []
            )
        ):
            failures.append(
                f"{contract_path}: historical evidence exact-seal registry is not exact"
            )

    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{fixture_path}: NYAY-14 seeded fixture is unreadable")
    else:
        outcome = fixture.get("expectedOutcome") if isinstance(fixture, dict) else None
        raw_logs = fixture.get("rawLogs") if isinstance(fixture, dict) else None
        groups = fixture.get("assertionGroups") if isinstance(fixture, dict) else None
        categories = {
            row.get("category")
            for row in raw_logs or []
            if isinstance(row, dict)
        }
        if (
            fixture.get("claimedVerdict") != "PASS"
            or not isinstance(outcome, dict)
            or outcome.get("verdict") != "FAIL"
            or outcome.get("mergeAuthorized") is not False
            or "chromium" in categories
            or not isinstance(groups, list)
            or not any(
                isinstance(group, dict) and group.get("executed") == 0
                for group in groups
            )
            or not {"MISSING_RAW_LOG", "ZERO_EXECUTED"}.issubset(
                set(outcome.get("codes", []))
            )
        ):
            failures.append(
                f"{fixture_path}: NYAY-14 seeded fail-closed fixture is not exact"
            )
    return failures


def check_nyay21_history_purge_contract(
    overrides: dict[str, Path] | None = None,
) -> list[str]:
    """Seal the non-executing NYAY-21 planner, contracts, and operator packet."""

    failures: list[str] = []
    selected = dict(NYAY21_HISTORY_PURGE_FILES)
    if overrides:
        unknown = set(overrides) - set(selected)
        if unknown:
            failures.append(
                "NYAY-21 history-purge contract received unknown source overrides: "
                f"{sorted(unknown)}"
            )
        selected.update({key: value for key, value in overrides.items() if key in selected})

    for label, path in selected.items():
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: NYAY-21 {label} source is missing or unsafe")
            continue
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            failures.append(f"{path}: NYAY-21 {label} source is unreadable")
            continue
        if actual != EXPECTED_NYAY21_HISTORY_PURGE_SHA256[label]:
            failures.append(
                f"{path}: NYAY-21 {label} SHA-256 differs from the sealed contract"
            )

    contract_path = selected["contract"]
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{contract_path}: NYAY-21 contract is unreadable")
    else:
        expected_arguments = [
            "--sensitive-data-removal",
            "--invert-paths",
            "--preserve-commit-hashes",
            "--replace-refs",
            "delete-no-add",
            "--prune-empty",
            "auto",
            "--prune-degenerate",
            "auto",
            "--path",
            "backend/legalsaathi_dev.db-shm",
            "--path",
            "backend/legalsaathi_dev.db-wal",
        ]
        expected_approval_policy = {
            "registrySchemaVersion": "nyay21-approval-consumption/v1",
            "ownerApprover": "Rajeev Barnwal",
            "technicalSecurityPrivacyApprover": "Claude Code",
            "requiredRoles": ["repository-owner", "security-privacy"],
            "sameSecurityPrivacyApproverAcrossGates": True,
            "approvalIdFormat": "NYAY21-(REWRITE|FORCE)-UUIDv4",
            "approvalUuidDistinctAcrossGates": True,
            "approvalRecordSha256Required": True,
            "approvalRecordsDistinctAcrossGates": True,
            "authoritativeSealRecomputation": True,
            "singleUse": True,
        }
        expected_required_gate_ids = [
            "nyayone-registration-required",
            "nyayone-wave1-required",
            "nyayone-wave2-required",
            "nyayone-wave3-required",
            "nyayone-wave4-required",
            "nyayone-wave5-required",
            "nyayone-policy-required",
        ]
        if (
            not isinstance(contract, dict)
            or contract.get("schemaVersion") != "nyay21-history-purge/v1"
            or contract.get("repository") != "rajeevbarnwal/NyayOne"
            or contract.get("defaultMode") != "plan-only"
            or contract.get("visibilityInvariant") != "PRIVATE"
            or contract.get("filterRepoVersion") != "a40bce548d2c"
            or contract.get("sourceHead")
            != "454a40784ee2e084d9a756a713f287b627f1c4d4"
            or contract.get("reachableCommitCount") != 321
            or contract.get("expectedAffectedCommitCount") != 267
            or contract.get("expectedChangedCommitCount") != 266
            or contract.get("expectedPrunedCommitCount") != 1
            or contract.get("expectedPostRewriteCommitCount") != 320
            or contract.get("signedCommitCount") != 40
            or contract.get("signatureDisposition")
            != "git-filter-repo-strips-40-gpg-signatures; preserve old signed objects only in the restricted backup under force-push-plus-30-days governance, document the historical attestation break, and sign forward from the rewritten head"
            or contract.get("authoritativeRefSeal")
            != {
                "artifact": "docs/operations/nyay21-history-purge/AUTHORITATIVE_REF_SEAL_20260904.json",
                "artifactCanonicalSha256": "2c7f3e20e2b53a7c7b866e6d8b5cd4b87902d3f9eeaede9d56e3dbf3a72b1e71",
                "refInventorySha256": "292a8bbaeba262de21c700546790e3c2b0e6c55f0174b4f5e9098b125be7edc7",
                "concreteRefCount": 42,
                "rowsIncludingSymbolicHead": 43,
            }
            or contract.get("rulesetRestoration")
            != {
                "rulesetId": 20888530,
                "payloadPairArtifact": "docs/operations/nyay21-history-purge/RULESET_PAYLOAD_PAIR_20260904.json",
                "fullCanonicalGetDigestRequired": True,
                "restorationTrapRequired": True,
            }
            or contract.get("atomicDryRun")
            != {
                "required": True,
                "closedWorldReadBackRefCount": 42,
                "exactLeasePerPublishableRef": True,
                "remoteMutationPermitted": False,
            }
            or contract.get("filterRepoArguments") != expected_arguments
            or contract.get("approvalGates")
            != ["rewrite-local-mirror", "atomic-force-with-lease"]
            or contract.get("approvalPolicy") != expected_approval_policy
            or contract.get("requiredGateIds") != expected_required_gate_ids
            or not isinstance(contract.get("targets"), list)
            or len(contract["targets"]) != 2
        ):
            failures.append(f"{contract_path}: NYAY-21 contract schema is not exact")

    gate_path = selected["gate"]
    try:
        tree = ast.parse(gate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        failures.append(f"{gate_path}: NYAY-21 planner cannot be statically audited")
    else:
        forbidden_imports = {"subprocess", "socket", "requests", "urllib", "http", "shutil"}
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        if imported.intersection(forbidden_imports):
            failures.append(
                f"{gate_path}: NYAY-21 planner contains an execution or network import"
            )
    return failures


def check_nyay18_browser_gate_contract(
    orchestrator_path: Path = NYAY18_BROWSER_ORCHESTRATOR,
    browser_path: Path = NYAY18_BROWSER_GATE,
    preview_path: Path = NYAY18_BROWSER_PREVIEW_SERVER,
    contract_path: Path = NYAY18_BROWSER_CONTRACT,
    contract_test_path: Path = NYAY18_BROWSER_CONTRACT_TEST,
    package_path: Path = FRONTEND_PACKAGE,
) -> list[str]:
    """Seal the executable production-Chromium producer reached by NYAY-18 CI."""

    failures: list[str] = []
    source_texts: dict[Path, str] = {}
    pinned_files = (
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_SHA256,
            "NYAY-18 browser orchestrator",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_SHA256,
            "NYAY-18 browser gate",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_SERVER_SHA256,
            "NYAY-18 browser preview canary server",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_SHA256,
            "NYAY-18 browser assertion contract",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_SHA256,
            "NYAY-18 browser assertion contract tests",
        ),
    )
    for path, expected_sha256, label in pinned_files:
        if not path.is_file() or path.is_symlink():
            failures.append(f"{path}: {label} is missing or unsafe")
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"{path}: {label} is unreadable")
            continue
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            failures.append(f"{path}: {label} SHA-256 differs from the sealed contract")
        try:
            source_texts[path] = raw.decode("utf-8")
        except UnicodeError:
            failures.append(f"{path}: {label} must be UTF-8 text")

    semantic_contracts = (
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_EXACT_HEAD,
            "exact-head environment plumbing",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_EXACT_HEAD,
            "exact-head evidence semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_EXACT_HEAD,
            "exact-head evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_EXACT_HEAD,
            "exact-head contract-test semantics",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_SEMANTICS,
            "preview credential-canary semantics",
        ),
        (
            orchestrator_path,
            EXPECTED_NYAY18_BROWSER_ORCHESTRATOR_PREVIEW_DIGEST,
            "preview-source digest plumbing",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_PREVIEW_DIGEST,
            "preview-source digest semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_PREVIEW_DIGEST,
            "preview-source evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_PREVIEW_DIGEST,
            "preview-source contract-test semantics",
        ),
        (
            preview_path,
            EXPECTED_NYAY18_BROWSER_PREVIEW_INSTALL_SHELL,
            "install-shell preview telemetry semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_INSTALL_SHELL,
            "install-shell credential-canary semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_INSTALL_SHELL,
            "install-shell evidence contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_INSTALL_SHELL,
            "install-shell contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_TWO_REALM_PRIVACY,
            "two-realm privacy-instrumentation contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_FINITE_LEADING_PURGE,
            "finite leading-key purge semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_FINITE_LEADING_PURGE,
            "finite leading-key purge contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_FINITE_LEADING_PURGE,
            "finite leading-key purge contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_ACTOR_ROTATION,
            "actor-rotation rediscovery semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_ACTOR_ROTATION,
            "actor-rotation rediscovery contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_ACTOR_ROTATION,
            "actor-rotation rediscovery contract-test semantics",
        ),
        (
            browser_path,
            EXPECTED_NYAY18_BROWSER_GATE_AUTHORITY_TRANSITIONS,
            "authority-loss transition semantics",
        ),
        (
            contract_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_AUTHORITY_TRANSITIONS,
            "authority-loss transition contract semantics",
        ),
        (
            contract_test_path,
            EXPECTED_NYAY18_BROWSER_CONTRACT_TEST_AUTHORITY_TRANSITIONS,
            "authority-loss transition contract-test semantics",
        ),
    )
    for path, required_fragments, label in semantic_contracts:
        source = source_texts.get(path)
        if source is not None and any(
            fragment not in source for fragment in required_fragments
        ):
            failures.append(f"{path}: NYAY-18 {label} are not exact")

    browser_source = source_texts.get(browser_path)
    contract_source = source_texts.get(contract_path)
    contract_test_source = source_texts.get(contract_test_path)
    # This row proves reused contract/mutant integrity only. The canonical
    # NYAY-5 workflow remains independently present, hash-bound and required.
    nyay5_separation_exact = (
        browser_source is not None
        and "failureStage = 'inherited_nyay5_contract_integrity';" in browser_source
        and "record('inherited_nyay5_contract_integrity'" in browser_source
        and contract_source is not None
        and "inherited_nyay5_contract_integrity: validInheritedNyay5Contract"
        in contract_source
        and "'inherited-nyay5-contract-failed'" in contract_source
        and contract_test_source is not None
        and "'inherited_nyay5_contract_integrity'" in contract_test_source
        and all(
            "inherited_nyay5_oracles_green" not in source
            for source in (browser_source, contract_source, contract_test_source)
        )
    )
    if not nyay5_separation_exact:
        failures.append(
            "NYAY-18 browser chain: NYAY-5 contract-integrity separation is not exact"
        )

    legacy_brand_runtime_exact = (
        browser_source is not None
        and browser_source.count(r"legal[\s._-]*saathi") >= 3
        and r"legal\s*saathi" not in browser_source
        and "runLegacyBrandSeparatorCanary" in browser_source
        and contract_source is not None
        and "metrics.brandSeparatorCanariesDetected === 6" in contract_source
        and "'brand-separator-canary-missed'" in contract_source
        and contract_test_source is not None
        and "'brand-separator-canary-missed'" in contract_test_source
    )
    if not legacy_brand_runtime_exact:
        failures.append(
            "NYAY-18 browser chain: legacy-brand separator runtime semantics are not exact"
        )

    if orchestrator_path.is_file() and not orchestrator_path.is_symlink():
        try:
            executable_bits = orchestrator_path.stat().st_mode & 0o111
        except OSError:
            executable_bits = 0
        if executable_bits != 0o111:
            failures.append(
                f"{orchestrator_path}: NYAY-18 browser orchestrator is not executable"
            )

    if not package_path.is_file() or package_path.is_symlink():
        failures.append(f"{package_path}: frontend package contract is missing or unsafe")
        return failures
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        failures.append(f"{package_path}: frontend package contract is unreadable")
        return failures
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict):
        failures.append(f"{package_path}: frontend scripts must be a mapping")
        return failures
    gate_name = "qa:nyay18:browser-namespace"
    if scripts.get(gate_name) != EXPECTED_NYAY18_BROWSER_PACKAGE_COMMAND:
        failures.append(
            f"{package_path}: NYAY-18 browser package command differs from the exact contract"
        )
    for hook in (f"pre{gate_name}", f"post{gate_name}"):
        if hook in scripts:
            failures.append(
                f"{package_path}: NYAY-18 browser package command may not have an npm lifecycle wrapper"
            )
    return failures


def _duplicate_mapping_keys(text: str) -> list[str]:
    """Reject duplicate keys in the repository's intentionally strict YAML subset."""

    failures: list[str] = []
    stack: list[tuple[int, str]] = []
    seen: dict[tuple[str, ...], set[str]] = {}
    sequence_counters: dict[tuple[tuple[str, ...], int], int] = {}
    block_scalar_indent: int | None = None
    mapping = re.compile(
        r"^(?P<indent> *)(?P<sequence>-\s+)?(?P<key>[A-Za-z0-9_-]+):(?P<value>.*)$"
    )

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if block_scalar_indent is not None:
            if indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        match = mapping.match(raw)
        if not match:
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = tuple(token for _, token in stack)
        if match.group("sequence"):
            counter_key = (parent, indent)
            number = sequence_counters.get(counter_key, 0) + 1
            sequence_counters[counter_key] = number
            stack.append((indent, f"sequence-{number}"))
            parent = tuple(token for _, token in stack)
        key = match.group("key")
        keys = seen.setdefault(parent, set())
        if key in keys:
            failures.append(f"duplicate YAML mapping key: {key}")
        keys.add(key)

        value = match.group("value").strip()
        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            block_scalar_indent = indent
        elif not value:
            stack.append((indent, key))
    return failures


def check_workflow(path: Path) -> list[str]:
    if path.name == "nyay42-optimization-observe.yml":
        # Exact additive non-required observer; existing producers, semantic
        # seals and seven required contexts are unchanged by this rollout.
        expected = "334e5a722bd40c3a107d92654afe88fe3a041dfbf2b7bd47df56c07e63859725"
        return [] if hashlib.sha256(path.read_bytes()).hexdigest() == expected else [
            f"{path}: NYAY-42 observation workflow differs from its exact sealed contract"
        ]
    if path.name == "nyay13-independent-qa-observe.yml":
        # Additive, non-required rollout surface; existing fail-closed workflow
        # rules and seven ruleset contexts are not relaxed. Seal all bytes.
        expected = "969926b59df5a2e20ea5590e4b1c87f30f590108700b7612d3a3319a0ef68a3e"
        return [] if hashlib.sha256(path.read_bytes()).hexdigest() == expected else [
            f"{path}: NYAY-13 observation workflow differs from its exact sealed contract"
        ]
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    if path.name not in CANONICAL_WORKFLOW_FILES:
        failures.append(f"{path}: workflow filename is not canonical")
    failures.extend(_structural_workflow_failures(text, path))
    failures.extend(f"{path}: {failure}" for failure in _duplicate_mapping_keys(text))

    canonical_yaml_rejections = {
        "noncanonical YAML key spacing": r"^\s*(?:-\s*)?[A-Za-z0-9_-]+\s+:.*$",
        "quoted YAML mapping key": r"^\s*(?:-\s*)?[\"'][^\"'\n]+[\"']\s*:",
        "inline YAML mapping": r"^\s*(?:-\s*)?[A-Za-z0-9_-]*\s*:\s*\{.*$|^\s*-\s*\{.*$",
        "YAML anchor, alias or merge key": r"^\s*(?:<<:|[-A-Za-z0-9_]+:\s*[&*]|-\s*[&*]).*$",
        "explicit YAML mapping key": r"^\s*[?:](?:\s|$)",
        "explicit YAML type tag": r"(?:^|:\s+)!![A-Za-z0-9_.:/-]+",
        "non-executing shell override": r"^\s*shell:\s*(?:true|false)(?:\s+\{0\})?\s*$",
    }
    for label, pattern in canonical_yaml_rejections.items():
        if re.search(pattern, text, re.MULTILINE):
            failures.append(f"{path}: forbidden {label}")
    if re.search(r"\$\{\{[^}\n]*\bsecrets\b", text, re.IGNORECASE):
        failures.append(f"{path}: forbidden repository secret reference")

    required_fragments = {
        "least-privilege token": "permissions:\n  contents: read",
        "PRs target main": "pull_request:\n    branches: [main]",
        "pushes target main": "push:\n    branches: [main]",
        "manual dispatch": "workflow_dispatch:",
        "concurrency": "concurrency:",
        "required aggregator": "\n  required:\n",
    }
    for label, fragment in required_fragments.items():
        if fragment not in text:
            failures.append(f"{path}: missing {label}")

    forbidden_fragments = {
        "pull_request_target": "pull_request_target:",
        "write-all token permission": "permissions: write-all",
        "write token permission": "contents: write",
        "path-filtered required checks": "    paths:",
        "path-ignored required checks": "    paths-ignore:",
        "fail-open step": "continue-on-error: true",
        "missing evidence warning": "if-no-files-found: warn",
        "mutable runner image": "runs-on: ubuntu-latest",
        "repository secret reference": "${{ secrets.",
        "unpinned pip upgrade": "pip install --upgrade pip",
    }
    for label, fragment in forbidden_fragments.items():
        if fragment in text:
            failures.append(f"{path}: forbidden {label}")

    forbidden_patterns = {
        "continue-on-error override": r"^\s*-?\s*continue-on-error\s*:",
        "statically disabled job or step": r"^\s*-?\s*if:\s*.*\bfalse\b.*$",
        "inline write permission": r"^\s*permissions:\s*\{[^}\n]*\b[a-zA-Z0-9_-]+\s*:\s*[\"']?write[\"']?\b[^}\n]*\}\s*$",
    }
    for label, pattern in forbidden_patterns.items():
        if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
            failures.append(f"{path}: forbidden {label}")

    for ref in ACTION_REF.findall(text):
        if not PINNED_ACTION.fullmatch(ref):
            failures.append(f"{path}: action is not pinned to 40 hex characters: {ref}")
        if ref not in ALLOWED_ACTIONS:
            failures.append(f"{path}: action identity is not allowlisted: {ref}")

    for ref in IMAGE_REF.findall(text):
        if not PINNED_IMAGE.fullmatch(ref):
            failures.append(f"{path}: service image is not pinned to sha256: {ref}")
        if ref not in ALLOWED_SERVICE_IMAGE_REFS:
            failures.append(f"{path}: service image reference is not allowlisted")

    runners = re.findall(r"^\s*runs-on:\s*([^\s#]+)", text, re.MULTILINE)
    if not runners:
        failures.append(f"{path}: workflow has no explicit runner")
    for runner in runners:
        if runner not in ALLOWED_RUNNERS:
            failures.append(f"{path}: runner identity is not allowlisted: {runner}")

    checkout_starts = [match.start() for match in re.finditer(r"uses:\s*actions/checkout@", text)]
    for start in checkout_starts:
        block = text[start : start + 260]
        if "persist-credentials: false" not in block:
            failures.append(f"{path}: checkout must set persist-credentials: false")
        if "fetch-depth: 0" not in block:
            failures.append(f"{path}: checkout must set fetch-depth: 0")

    jobs_text = text.split("\njobs:\n", maxsplit=1)[1] if "\njobs:\n" in text else ""
    job_count = len(re.findall(r"^  [a-zA-Z0-9_-]+:\n", jobs_text, flags=re.MULTILINE))
    timeout_count = len(
        re.findall(r"^    timeout-minutes:\s*\d+", jobs_text, flags=re.MULTILINE)
    )
    if timeout_count < job_count:
        failures.append(
            f"{path}: every job needs timeout-minutes ({timeout_count}/{job_count})"
        )

    job_ids = set(re.findall(r"^  ([a-zA-Z0-9_-]+):\n", jobs_text, flags=re.MULTILINE))
    required_block = jobs_text.split("\n  required:\n", maxsplit=1)[1] if "\n  required:\n" in jobs_text else ""
    if not re.search(r"^    if:\s*\$\{\{ always\(\) \}\}\s*$", required_block, re.MULTILINE):
        failures.append(f"{path}: required aggregator must run with if: always()")
    needs_match = re.search(r"^    needs:\s*\[([^\]]*)\]", required_block, re.MULTILINE)
    actual_needs = {
        value.strip() for value in needs_match.group(1).split(",") if value.strip()
    } if needs_match else set()
    expected_needs = job_ids - {"required"}
    if actual_needs != expected_needs:
        failures.append(
            f"{path}: required aggregator needs {sorted(actual_needs)}, expected {sorted(expected_needs)}"
        )
    result_contract = (
        "RESULTS: ${{ toJSON(needs) }}",
        'if not results or any(value != "success" for value in results.values()):',
        'sys.exit("one or more required jobs did not succeed")',
    )
    if any(fragment not in required_block for fragment in result_contract):
        failures.append(f"{path}: required aggregator lacks the fail-closed needs result contract")
    required_steps = _step_blocks(required_block)
    if len(required_steps) != 1:
        failures.append(f"{path}: required aggregator must contain exactly one step")
    else:
        required_step = required_steps[0]
        if re.search(r"^        (?:if|shell):", required_step, re.MULTILINE):
            failures.append(
                f"{path}: required aggregator step may not override its condition or shell"
            )
        result_env = re.findall(
            r"^          RESULTS:\s*(.*?)\s*$", required_step, re.MULTILINE
        )
        if result_env != ["${{ toJSON(needs) }}"]:
            failures.append(f"{path}: required aggregator needs the exact needs JSON input")
        if _run_payload(required_step) != EXPECTED_REQUIRED_RUN:
            failures.append(f"{path}: required aggregator command differs from the exact fail-closed contract")

    for match in re.finditer(
        r"^\s+[a-zA-Z0-9_-]+:\s*[\"']?write[\"']?\s*$",
        text,
        re.MULTILINE,
    ):
        failures.append(f"{path}: workflow requests a write permission: {match.group(0).strip()}")
    if re.search(r"^\s*permissions:\s*write-all\s*$", text, re.MULTILINE):
        failures.append(f"{path}: workflow requests permissions: write-all")

    contracts = EVIDENCE_CONTRACTS.get(path.name, {})
    upload_jobs: set[str] = set()
    job_matches = list(re.finditer(r"^  ([a-zA-Z0-9_-]+):\n", jobs_text, re.MULTILINE))
    for index, match in enumerate(job_matches):
        job_id = match.group(1)
        end = job_matches[index + 1].start() if index + 1 < len(job_matches) else len(jobs_text)
        job_block = jobs_text[match.start():end]
        steps = _step_blocks(job_block)
        upload_indexes = [
            step_index
            for step_index, step in enumerate(steps)
            if re.search(
                r"^(?:      - |        )uses:\s*actions/upload-artifact@",
                step,
                re.MULTILINE,
            )
        ]
        if not upload_indexes:
            continue
        upload_jobs.add(job_id)
        diagnostic_contract = FAILURE_DIAGNOSTIC_UPLOADS.get(
            (path.name, job_id)
        )
        diagnostic_indexes = []
        if diagnostic_contract is not None:
            diagnostic_indexes = [
                step_index
                for step_index in upload_indexes
                if re.search(
                    r"^      - name:\s*"
                    + re.escape(str(diagnostic_contract["name"]))
                    + r"\s*$",
                    steps[step_index],
                    re.MULTILINE,
                )
            ]
            if len(diagnostic_indexes) != 1:
                failures.append(
                    f"{path}: job {job_id} needs exactly one privacy-safe diagnostic upload"
                )
            elif (
                diagnostic_indexes[0] == 0
                or _run_payload(steps[diagnostic_indexes[0] - 1])
                != diagnostic_contract["producer"]
            ):
                failures.append(
                    f"{path}: job {job_id} diagnostic upload must immediately follow its producer"
                )
        canonical_upload_indexes = [
            step_index
            for step_index in upload_indexes
            if step_index not in diagnostic_indexes
        ]
        if diagnostic_contract is not None and job_id not in contracts:
            if canonical_upload_indexes:
                failures.append(
                    f"{path}: job {job_id} diagnostic-only contract forbids other artifact uploads"
                )
            continue
        if len(canonical_upload_indexes) != 1:
            failures.append(
                f"{path}: job {job_id} must have exactly one artifact upload "
                "for the canonical attestation"
            )
        if job_id not in contracts:
            if (path.name, job_id) in DIRECT_EVIDENCE_UPLOAD_PATHS:
                # The full direct chain is bound structurally above, including
                # raw sealing, raw verification, textual preparation, privacy
                # scanning, uploadable sealing and the exact upload condition.
                continue
            failures.append(f"{path}: job {job_id} has no canonical evidence contract")
            continue

        source, destination, profile = contracts[job_id]
        if not canonical_upload_indexes:
            continue
        upload_index = canonical_upload_indexes[0]
        canonical_job = _canonical_shell(job_block)
        if "prepare_uploadable_evidence.py" not in canonical_job:
            failures.append(
                f"{path}: job {job_id} is missing structured evidence preparation"
            )
        if "evidence_manifest.py --seal" not in canonical_job:
            failures.append(
                f"{path}: job {job_id} is missing evidence manifest seal step"
            )
        ids = [_step_id(step) for step in steps]
        required_ids = (
            "evidence_prepare",
            "evidence_manifest",
            "evidence_privacy",
            "evidence_integrity",
            "evidence_schema",
        )
        id_indexes: list[int] = []
        for required_id in required_ids:
            indexes = [step_index for step_index, value in enumerate(ids) if value == required_id]
            if len(indexes) != 1:
                failures.append(
                    f"{path}: job {job_id} needs exactly one {required_id} step"
                )
            else:
                id_indexes.append(indexes[0])
        if len(id_indexes) != len(required_ids):
            continue
        result_indexes = [
            step_index
            for step_index, value in enumerate(ids)
            if value == "evidence_result"
        ]
        if len(result_indexes) != 1:
            failures.append(
                f"{path}: job {job_id} needs exactly one evidence_result step"
            )
            continue
        result_index = result_indexes[0]
        if id_indexes + [upload_index, result_index] != list(
            range(id_indexes[0], id_indexes[0] + len(required_ids) + 2)
        ):
            failures.append(
                f"{path}: job {job_id} evidence chain must be adjacent and ordered "
                "prepare, seal, scan, reverify, validate, upload, require-pass"
            )

        expected_commands = (
            f"prepare_uploadable_evidence.py --profile {profile} {source} {destination}",
            f"evidence_manifest.py --seal {destination}",
            f"scan_evidence.py {destination}",
            f"evidence_manifest.py --verify {destination}",
            f"prepare_uploadable_evidence.py --validate-attestation {destination}",
        )
        for required_id, step_index, expected_command in zip(
            required_ids, id_indexes, expected_commands
        ):
            step = steps[step_index]
            if re.search(
                r"^        (?:env|shell|working-directory):", step, re.MULTILINE
            ):
                failures.append(
                    f"{path}: job {job_id} {required_id} may not override its environment, shell or working directory"
                )
            always = re.findall(
                r"^        if:\s*(.*?)\s*$", step, re.MULTILINE
            )
            if always != ["${{ always() }}"]:
                failures.append(
                    f"{path}: job {job_id} {required_id} must use exact if: always()"
                )
            command = _run_payload(step)
            if command is None:
                failures.append(
                    f"{path}: job {job_id} {required_id} needs one explicit command"
                )
                continue
            canonical = _canonical_shell(command)
            if re.search(r"(?:\|\||&&|;|\n)", command):
                failures.append(
                    f"{path}: job {job_id} {required_id} contains a shell control operator"
                )
            exact_command = re.compile(
                r"^python(?:3)? \$GITHUB_WORKSPACE/scripts/ci/"
                + re.escape(expected_command)
                + r"$"
            )
            if not exact_command.fullmatch(canonical):
                failures.append(
                    f"{path}: job {job_id} {required_id} is not the exact canonical evidence command"
                )
            script_name = expected_command.split(maxsplit=1)[0]
            if canonical.count(script_name) != 1:
                failures.append(
                    f"{path}: job {job_id} {required_id} must invoke its evidence tool exactly once"
                )

        upload_step = steps[upload_index]
        upload_conditions = re.findall(
            r"^        if:\s*(.*?)\s*$", upload_step, re.MULTILINE
        )
        if upload_conditions != [EXPECTED_UPLOAD_IF]:
            failures.append(
                f"{path}: job {job_id} upload condition must be the exact fail-closed contract"
            )
        path_values = re.findall(
            r"^          path:\s*(.*?)\s*$", upload_step, re.MULTILINE
        )
        normalized_paths = [_canonical_shell(value) for value in path_values]
        if normalized_paths != [destination]:
            failures.append(
                f"{path}: job {job_id} upload path must be one exact canonical scalar"
            )
        if re.findall(
            r"^          if-no-files-found:\s*(.*?)\s*$", upload_step, re.MULTILINE
        ) != ["error"]:
            failures.append(
                f"{path}: job {job_id} upload must fail when evidence is missing"
            )
        if re.findall(
            r"^          include-hidden-files:\s*(.*?)\s*$", upload_step, re.MULTILINE
        ) != ["false"]:
            failures.append(
                f"{path}: job {job_id} upload must exclude hidden files"
            )

        result_step = steps[result_index]
        if re.search(
            r"^        (?:env|shell|working-directory):", result_step, re.MULTILINE
        ):
            failures.append(
                f"{path}: job {job_id} evidence_result may not override its environment, shell or working directory"
            )
        if re.findall(
            r"^        if:\s*(.*?)\s*$", result_step, re.MULTILINE
        ) != ["${{ always() }}"]:
            failures.append(
                f"{path}: job {job_id} evidence_result must use exact if: always()"
            )
        result_command = _run_payload(result_step)
        expected_result = re.compile(
            r"^python(?:3)? \$GITHUB_WORKSPACE/scripts/ci/"
            r"prepare_uploadable_evidence\.py --require-pass "
            + re.escape(destination)
            + r"$"
        )
        if (
            result_command is None
            or not expected_result.fullmatch(_canonical_shell(result_command))
        ):
            failures.append(
                f"{path}: job {job_id} evidence_result command is not exact"
            )

    for expected_job in sorted(set(contracts) - upload_jobs):
        failures.append(
            f"{path}: canonical evidence job {expected_job} is missing its artifact upload"
        )

    return failures


def check_nyay4_quarantine_workflow(path: Path) -> list[str]:
    """Validate the one visible, non-required quarantine workflow exactly."""

    failures = check_workflow(path)
    expected_required_gate_failures = (
        "missing pushes target main",
        "missing required aggregator",
        "required aggregator must run with if: always()",
        "required aggregator needs ",
        "required aggregator lacks the fail-closed needs result contract",
        "required aggregator must contain exactly one step",
    )
    failures = [
        failure
        for failure in failures
        if not any(marker in failure for marker in expected_required_gate_failures)
    ]
    text = path.read_text(encoding="utf-8")
    exact_fragments = {
        "pull-request trigger": "  pull_request:\n    branches: [main]",
        "scheduled evidence trigger": '  schedule:\n    - cron: "17 3 * * *"',
        "manual evidence trigger": "  workflow_dispatch:",
        "quarantined assertion": NYAY4_QUARANTINED_ASSERTION_ID,
        "owner-approved reason": NYAY4_QUARANTINE_REASON,
        "strict producer flag": "--require-quarantined-assertion",
        "strict diagnostic stage": "Run quarantined assertion in strict evidence mode",
        "explicit unavailable diagnostic": "Initialize explicit not-yet-executed diagnostic",
        "pgvector control fixture": "Enable pgvector in the exact control database",
        "pgvector extension command": '-c "CREATE EXTENSION IF NOT EXISTS vector;"',
        "always upload": "        if: ${{ always() }}",
        "artifact name": "nyay4-cookie-origin-reload-symmetry-diagnostic",
        "artifact path": (
            "${{ github.workspace }}/backend/test-results/"
            "nyay4-ci-flaky/summary.json"
        ),
        "missing artifact fails": "if-no-files-found: error",
    }
    for label, fragment in exact_fragments.items():
        if text.count(fragment) != 1:
            failures.append(f"{path}: quarantine workflow {label} is not exact")
    if "\n  push:\n" in text or "\n  required:\n" in text:
        failures.append(
            f"{path}: quarantine workflow must not impersonate a required gate"
        )
    strict_command = (
        "NYAY4_POSTGRES_GATE=1 python scripts/nyay4_postgres_otp_gate.py "
        '--execute --database-url "$DATABASE_URL" '
        "--require-quarantined-assertion "
        "--output test-results/nyay4-ci-flaky/summary.json"
    )
    if text.count(f"        run: {strict_command}") != 1:
        failures.append(f"{path}: quarantine workflow producer command is not exact")
    if any(marker in text for marker in ("|| true", "continue-on-error", "pytest.skip", "xfail")):
        failures.append(f"{path}: quarantine workflow suppresses its oracle")
    return failures


def _python_alembic_calls(tree: ast.AST) -> list[ast.Call]:
    command_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
        and isinstance(node.value, (ast.List, ast.Tuple))
        and any(
            isinstance(item, ast.Constant) and item.value == "alembic"
            for item in ast.walk(node.value)
        )
    }
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        direct_api = any(
            isinstance(item, ast.Name)
            and item.id in {"alembic", "alembic_command"}
            for item in ast.walk(node.func)
        )
        command = node.args[0] if node.args else None
        command_literal = command is not None and any(
            isinstance(item, ast.Constant) and item.value == "alembic"
            for item in ast.walk(command)
        )
        assigned_command = command is not None and any(
            isinstance(item, ast.Name) and item.id in command_names
            for item in ast.walk(command)
        )
        if direct_api or command_literal or assigned_command:
            calls.append(node)
    return calls


def _call_has_exact_isolated_environment(call: ast.Call) -> bool:
    environment = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "env"),
        None,
    )
    if not isinstance(environment, ast.Dict):
        return False
    matches = [
        index
        for index, (key, value) in enumerate(
            zip(environment.keys, environment.values)
        )
        if isinstance(key, ast.Constant)
        and key.value == NYAY19_ISOLATED_MIGRATION_ENV
        and isinstance(value, ast.Constant)
        and value.value == "1"
    ]
    # The exact authority must be the final dictionary item. A later **mapping
    # could otherwise replace it at runtime while leaving a misleading literal
    # in the source for a weak static checker to find.
    return matches == [len(environment.keys) - 1]


def _production_wrapper_is_fail_closed(tree: ast.AST, call: ast.Call) -> bool:
    call_line = getattr(call, "lineno", 0)
    environment_keyword = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "env"),
        None,
    )
    command = call.args[0]
    command_nodes = list(ast.walk(command))
    if (
        not isinstance(environment_keyword, ast.Name)
        or environment_keyword.id != "environment"
        or not any(
            isinstance(node, ast.Constant) and node.value == "upgrade"
            for node in command_nodes
        )
        or not any(
            isinstance(node, ast.Name) and node.id == "TARGET_REVISION"
            for node in command_nodes
        )
    ):
        return False

    copied_environment = False
    removed_isolated_authority = False
    forced_production_approval = False
    for node in ast.walk(tree):
        if getattr(node, "lineno", call_line + 1) >= call_line:
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "environment"
            for target in node.targets
        ):
            copied_environment = (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "dict"
                and bool(node.value.args)
                and isinstance(node.value.args[0], ast.Attribute)
                and isinstance(node.value.args[0].value, ast.Name)
                and node.value.args[0].value.id == "os"
                and node.value.args[0].attr == "environ"
            )
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            isolated_in_iterable = any(
                isinstance(item, ast.Name)
                and item.id == "ISOLATED_EXECUTION_ENV"
                for item in ast.walk(node.iter)
            )
            removes_loop_name = any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == "environment"
                and item.func.attr == "pop"
                and bool(item.args)
                and isinstance(item.args[0], ast.Name)
                and item.args[0].id == node.target.id
                for statement in node.body
                for item in ast.walk(statement)
            )
            removed_isolated_authority = (
                removed_isolated_authority
                or (isolated_in_iterable and removes_loop_name)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "environment"
            and node.func.attr == "update"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            values: dict[str, object] = {}
            for key, value in zip(node.args[0].keys, node.args[0].values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    name = key.value
                elif isinstance(key, ast.Name):
                    name = key.id
                else:
                    continue
                if isinstance(value, ast.Constant):
                    values[name] = value.value
            forced_production_approval = (
                forced_production_approval
                or values.get("APP_ENV") == "production"
                and values.get("FORCE_APPROVAL_ENV") == "1"
            )
    return copied_environment and removed_isolated_authority and forced_production_approval


def _shell_executable_source(source: str) -> str:
    return "\n".join(
        line.split("#", 1)[0]
        for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )


def check_alembic_execution_contracts(root: Path = ROOT) -> list[str]:
    """Inventory every shipped Alembic entry point and seal its authority."""

    failures: list[str] = []
    root = Path(root)
    python_callers: set[str] = set()
    python_root = root / "backend" / "scripts"
    # The owner-approved native producer is intentionally relocated under tests;
    # audit it explicitly without classifying unit-test Alembic mocks as callers.
    python_paths = set(python_root.rglob("*.py")) if python_root.is_dir() else set()
    python_paths.add(root / "backend/tests/nyay12_native_gate.py")
    if python_paths:
        for path in sorted(python_paths):
            if path.is_symlink():
                failures.append(f"{path}: Alembic script inventory may not contain symlinks")
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                failures.append(
                    f"{path}: Python script cannot be audited: {type(exc).__name__}"
                )
                continue
            calls = _python_alembic_calls(tree)
            if not calls:
                continue
            relative = path.relative_to(root).as_posix()
            python_callers.add(relative)
            if relative == "backend/scripts/nyay19_migrate.py":
                if len(calls) != 1 or not _production_wrapper_is_fail_closed(
                    tree, calls[0]
                ):
                    failures.append(
                        f"{path}: production Alembic wrapper must remove isolated authority and force exact approval"
                    )
                continue
            for call in calls:
                if not _call_has_exact_isolated_environment(call):
                    failures.append(
                        f"{path}:{getattr(call, 'lineno', 0)}: missing exact isolated subprocess authority"
                    )

    shell_callers: set[str] = set()
    shell_roots = (root / "backend" / "scripts", root / "scripts")
    shell_paths = {
        path
        for shell_root in shell_roots
        if shell_root.is_dir()
        for path in shell_root.rglob("*.sh")
    }
    for path in sorted(shell_paths):
        if path.is_symlink():
            failures.append(f"{path}: Alembic shell inventory may not contain symlinks")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            failures.append(f"{path}: shell script cannot be audited: {type(exc).__name__}")
            continue
        executable = _shell_executable_source(source)
        if (
            "-m alembic" not in executable
            and re.search(
                r"(?:^|[;&|(]\s*)alembic\s+(?:upgrade|downgrade|check|current|stamp)\b",
                executable,
                re.MULTILINE,
            ) is None
        ):
            continue
        relative = path.relative_to(root).as_posix()
        shell_callers.add(relative)
        classification = EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS.get(relative)
        if classification is None:
            failures.append(f"{path}: unclassified Alembic shell caller")
        elif classification == "isolated-postgresql":
            if re.findall(
                rf"^export {re.escape(NYAY19_ISOLATED_MIGRATION_ENV)}=1$",
                executable,
                re.MULTILINE,
            ) != [f"export {NYAY19_ISOLATED_MIGRATION_ENV}=1"]:
                failures.append(
                    f"{path}: missing exact isolated shell authority"
                )
        elif classification == "nyay5-owned-scratch-postgresql":
            canonical = _canonical_shell(re.sub(r"\\\s*\n", " ", executable))
            control_guard = _canonical_shell(
                'CONTROL_URL="${NYAY5_POSTGRES_CONTROL_URL:?NYAY5_POSTGRES_CONTROL_URL is required}"'
            )
            create_scratch = _canonical_shell(
                'PYTHONPATH="$ROOT/backend" "$PYTHON" '
                '"$ROOT/backend/scripts/nyay5_browser_gate_control.py" create '
                '--control-url "$CONTROL_URL" --state-file "$STATE_FILE" '
                '>"$PRIVATE_DIR/create-summary.json" 2>"$PRIVATE_DIR/create-error.log"'
            )
            isolated_upgrade = _canonical_shell(
                "APP_ENV=testing DATABASE_URL=\"$SCRATCH_URL\" "
                "REGISTRATION_SECRET='nyay5-browser-synthetic-registration-key-v1' "
                "REGISTRATION_LOOKUP_SECRET='nyay5-browser-synthetic-lookup-key-v1' "
                f"{NYAY19_ISOLATED_MIGRATION_ENV}=1 "
                '"$PYTHON" -m alembic upgrade head'
            )
            if (
                canonical.count(control_guard) != 1
                or canonical.count(create_scratch) != 1
                or canonical.count(isolated_upgrade) != 1
                or f"export {NYAY19_ISOLATED_MIGRATION_ENV}" in executable
            ):
                failures.append(
                    f"{path}: NYAY-5 Alembic caller lacks exact owned-scratch isolated authority"
                )
        elif classification == "local-sqlite":
            if (
                NYAY19_ISOLATED_MIGRATION_ENV in executable
                or 'export DATABASE_URL="sqlite+pysqlite:///$DB_FILE"' not in executable
                or "export APP_ENV=development" not in executable
            ):
                failures.append(
                    f"{path}: local SQLite Alembic caller must not receive PostgreSQL isolated authority"
                )

    workflow_root = root / ".github" / "workflows"
    seen_workflow_callers: set[tuple[str, str]] = set()
    if workflow_root.is_dir() and yaml is not None:
        workflow_paths = sorted(workflow_root.glob("*.yml")) + sorted(
            workflow_root.glob("*.yaml")
        )
        for path in workflow_paths:
            try:
                document = yaml.load(
                    path.read_text(encoding="utf-8"),
                    Loader=_NoDuplicateBaseLoader,
                )
            except (OSError, UnicodeError, yaml.YAMLError):
                failures.append(f"{path}: workflow cannot be audited for Alembic authority")
                continue
            document_mapping = _mapping(document)
            jobs = _mapping(document_mapping.get("jobs")) if document_mapping else None
            if jobs is None:
                failures.append(f"{path}: workflow jobs cannot be audited for Alembic authority")
                continue
            failures.extend(_nyay19_workflow_alembic_failures(path, jobs))
            seen_workflow_callers.update(
                (path.name, job_id)
                for job_id in jobs
                if (path.name, job_id) in EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS
            )

        for missing in sorted(
            set(EXPECTED_NYAY19_ALEMBIC_WORKFLOW_JOBS) - seen_workflow_callers
        ):
            failures.append(
                f"{workflow_root}: missing NYAY-19 isolated Alembic workflow caller {missing}"
            )
        if python_callers != EXPECTED_NYAY19_ALEMBIC_PYTHON_CALLERS:
            failures.append(
                f"{python_root}: Alembic Python caller inventory differs from the sealed contract; "
                f"found={sorted(python_callers)}"
            )
        if shell_callers != set(EXPECTED_NYAY19_ALEMBIC_SHELL_CALLERS):
            failures.append(
                f"{root}: Alembic shell caller inventory differs from the sealed contract; "
                f"found={sorted(shell_callers)}"
            )
    return failures


def main() -> int:
    workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not workflow_paths:
        print("no workflows found", file=sys.stderr)
        return 1

    failures: list[str] = []
    if {path.name for path in workflow_paths} != CANONICAL_WORKFLOW_FILES:
        failures.append(
            "workflow filename inventory differs from nine required gates plus the "
            "single quarantined evidence workflow and NYAY-13/42 observations"
        )
    failures.extend(check_db_gate_contract())
    failures.extend(check_nyay11_db_gate_contract())
    failures.extend(check_nyay4_browser_gate_contract())
    failures.extend(check_nyay22_browser_gate_contract())
    failures.extend(check_nyay22_postgres_gate_contract())
    failures.extend(check_nyay22_schema_artifact_contract())
    failures.extend(check_nyay22_nyay19_erasure_integration_contract())
    failures.extend(check_nyay19_browser_gate_contract())
    failures.extend(check_nyay5_gate_contract())
    failures.extend(check_nyay14_evidence_gate_contract())
    failures.extend(check_nyay21_history_purge_contract())
    failures.extend(check_nyay18_static_gate_contract())
    failures.extend(check_nyay18_browser_gate_contract())
    failures.extend(check_alembic_execution_contracts())
    failures.extend(
        failure
        for path in workflow_paths
        for failure in (
            check_nyay4_quarantine_workflow(path)
            if path.name == NYAY4_QUARANTINE_WORKFLOW_FILE
            else check_workflow(path)
        )
    )
    required_names: list[tuple[Path, str]] = []
    for path in workflow_paths:
        if path.name in {NYAY4_QUARANTINE_WORKFLOW_FILE, "nyay13-independent-qa-observe.yml", "nyay42-optimization-observe.yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^  required:\n    name:\s*([^\s#]+)", text, re.MULTILINE)
        if not match:
            failures.append(f"{path}: required aggregator needs an explicit stable name")
            continue
        name = match.group(1)
        required_names.append((path, name))
        if not re.fullmatch(r"nyayone-[a-z0-9-]+-required", name):
            failures.append(f"{path}: invalid required check name: {name}")
    counts = {name: sum(candidate == name for _, candidate in required_names) for _, name in required_names}
    for path, name in required_names:
        if counts[name] != 1:
            failures.append(f"{path}: duplicate required check name: {name}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(f"NyayOne workflow policy passed for {len(workflow_paths)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
